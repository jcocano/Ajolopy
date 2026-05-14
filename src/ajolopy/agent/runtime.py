"""``AgentRuntime`` — the run/stream engine behind the ``@Agent`` decorator.

The decorator builds one ``AgentRuntime`` per decorated class at decoration
time and binds it to the class. Instance methods ``run`` / ``stream`` close
over the runtime so per-instance state stays at the class level (the agent
config is shared across instances by design).

The runtime also owns the function-calling loop: when a provider response
carries ``tool_calls``, the runtime resolves each call against the agent's
registered ``@Tool`` bindings, dispatches them, appends ``tool_result``
messages to the conversation, and re-calls the provider until the response
is tool-free or ``max_tool_iterations`` is exceeded.

Observability is unconditional. Every ``run`` / ``stream`` invocation opens an
``agent.invoke {AgentName}`` root span; every provider call gets a
``chat {model}`` child span with OpenTelemetry GenAI semantic-convention
attributes; every tool dispatch gets an ``execute_tool {tool_name}`` grandchild
span. When the ``ajolopy[otel]`` SDK extra is not installed the spans are
cheap no-ops emitted by the api layer.
"""

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry.trace import Span, Status, StatusCode
from pydantic import ValidationError

if TYPE_CHECKING:
    from ajolopy.providers.types import ChunkUsage

from ajolopy.memory import Memory, resolve_memory
from ajolopy.observability import (
    AJOLOPY_AGENT_NAME,
    AJOLOPY_AGENT_OPERATION,
    AJOLOPY_STREAMING,
    GEN_AI_COMPLETION,
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROMPT,
    GEN_AI_REQUEST_MAX_TOKENS,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_TEMPERATURE,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_SYSTEM,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_NAME,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_CHAT,
    Catalog,
    agent_invoke_span_name,
    chat_span_name,
    execute_tool_span_name,
    get_tracer,
    is_content_capture_enabled,
)
from ajolopy.observability.pricing import get_active_catalog
from ajolopy.observability.pricing_emit import set_chat_cost_attrs, set_root_cost_total
from ajolopy.providers import (
    LLMProvider,
    LLMProviderError,
    Message,
    ProviderNotRegisteredError,
    Response,
    Tool,
    ToolCall,
    UnknownModelError,
    get_provider_class,
    resolve_provider,
)

from .errors import (
    AgentConfigError,
    AgentError,
    AgentProviderError,
    AgentToolLoopError,
)
from .tool import ToolBinding, discover_tools

_TRACER = get_tracer("ajolopy.agent")
_LOGGER = logging.getLogger(__name__)

# Default session id used when the agent is configured with memory and the
# caller does not partition sessions explicitly. AJ-24 may surface
# session-id routing through a richer Memory contract.
_DEFAULT_SESSION_ID = "default"


SystemPrompt = str | Callable[[str], str]
"""``system`` kwarg accepts a static string or a per-request callable."""

FallbackSpec = str | list[str] | Callable[[str], Awaitable[str] | str] | None
"""``fallback`` kwarg accepts a single model, a list, or a callable."""


class AgentRuntime:
    """Encapsulates run/stream/fallback/tracing for one decorated agent class.

    Construction (which happens inside ``Agent(...)`` at decoration time)
    resolves every model in the primary + fallback chain to a registered
    provider, instantiates each provider exactly once, and short-circuits
    with ``AgentConfigError`` on any failure. That keeps misconfigurations
    visible at bootstrap rather than at first request.
    """

    def __init__(
        self,
        *,
        agent_cls: type[Any],
        model: str,
        system: SystemPrompt,
        memory: object,
        cache: Literal["prompt"] | None,
        fallback: FallbackSpec,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[type[Any]] | None,
        max_tool_iterations: int,
        catalog: Catalog | None = None,
    ) -> None:
        if cache == "prompt" and callable(system):
            raise AgentConfigError(
                "cache='prompt' requires a static system prompt; a callable "
                "system prompt cannot be safely cached. Either drop cache or "
                "make the system kwarg a string."
            )
        if max_tool_iterations < 1:
            raise AgentConfigError(f"max_tool_iterations must be >= 1, got {max_tool_iterations}.")

        self._agent_cls = agent_cls
        self._agent_name = agent_cls.__name__
        self._system: SystemPrompt = system
        self._cache_prompt = cache == "prompt"
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_tool_iterations = max_tool_iterations

        bindings, extra_instances = discover_tools(agent_cls, tools)
        self._tool_bindings: list[ToolBinding] = bindings
        self._tool_by_name: dict[str, ToolBinding] = {b.metadata.name: b for b in bindings}
        self._extra_instances: dict[type[Any], Any] = extra_instances
        self._wire_tools: list[Tool] = [b.metadata.to_wire_tool() for b in bindings]

        # Resolve and instantiate every model's provider exactly once.
        fallback_models = self._normalize_fallback(fallback)
        self._fallback_callable = fallback if callable(fallback) else None
        self._models: list[tuple[str, LLMProvider]] = []
        provider_cache: dict[str, LLMProvider] = {}
        for model_str in [model, *fallback_models]:
            provider_key = self._resolve_provider_key(model_str)
            if provider_key not in provider_cache:
                provider_cache[provider_key] = self._instantiate_provider(provider_key)
            self._models.append((model_str, provider_cache[provider_key]))

        self._primary_provider_key = self._resolve_provider_key(model)
        self._memory: Memory | None = resolve_memory(memory)  # type: ignore[arg-type]

        # ``catalog`` defaults to None — pricing emission resolves the active
        # catalog lazily on first chat-span emission via :func:`get_active_catalog`.
        # That keeps decorator-time construction independent of the factory's
        # ``pricing_overrides`` plumbing (which runs later, at bootstrap).
        self._catalog: Catalog | None = catalog

    @staticmethod
    def _normalize_fallback(fallback: FallbackSpec) -> list[str]:
        if fallback is None or callable(fallback):
            return []
        if isinstance(fallback, str):
            return [fallback]
        return list(fallback)

    @staticmethod
    def _resolve_provider_key(model: str) -> str:
        try:
            return resolve_provider(model)
        except UnknownModelError as exc:
            raise AgentConfigError(
                f"Unknown model {model!r}: {exc}. Check the registered "
                f"routing prefixes or call register_route()."
            ) from exc

    @staticmethod
    def _instantiate_provider(provider_key: str) -> LLMProvider:
        try:
            cls = get_provider_class(provider_key)
        except ProviderNotRegisteredError as exc:
            raise AgentConfigError(
                f"Provider {provider_key!r} is registered as a routing "
                f"target but no concrete LLMProvider class is bound. Import "
                f"the corresponding ajolopy.providers.* package."
            ) from exc
        try:
            return cls()
        except Exception as exc:
            raise AgentConfigError(
                f"Failed to instantiate provider {provider_key!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # public methods called by the decorator-injected instance methods
    # ------------------------------------------------------------------

    async def run(self, agent_instance: Any, message: str) -> str:
        history = await self._load_history()
        prompt_messages = self._build_messages(history, message)
        last_error: BaseException | None = None
        wire_tools: list[Tool] | None = self._wire_tools or None
        # Per-invoke accumulator for chat-span costs. Each chat helper
        # appends one entry (float for known model, None for unknown). The
        # invoke span reads it once the body finishes to write the root
        # ``ajolopy.cost_usd.total`` attr.
        child_costs: list[float | None] = []

        with self._invoke_span(operation="run", streaming=False) as invoke_span:
            for model_str, provider in self._models:
                try:
                    final_text = await self._run_tool_loop(
                        agent_instance=agent_instance,
                        provider=provider,
                        model_str=model_str,
                        prompt_messages=prompt_messages,
                        wire_tools=wire_tools,
                        child_costs=child_costs,
                    )
                except LLMProviderError as exc:
                    last_error = exc
                    # Reset the message buffer between fallback attempts so a
                    # half-finished tool loop doesn't leak into the next try.
                    prompt_messages = self._build_messages(history, message)
                    continue
                await self._persist_turn(message, final_text)
                set_root_cost_total(invoke_span, child_costs)
                return final_text

            set_root_cost_total(invoke_span, child_costs)
            if self._fallback_callable is not None:
                return await self._run_callable_fallback(message)

            raise AgentProviderError(
                f"Agent {self._agent_name!r} exhausted all providers"
                f"{f' (last error: {last_error})' if last_error is not None else ''}."
            ) from last_error

    def stream(self, agent_instance: Any, message: str) -> AsyncIterator[str]:
        async def _iterator() -> AsyncIterator[str]:
            history = await self._load_history()
            wire_tools: list[Tool] | None = self._wire_tools or None
            last_error: BaseException | None = None
            child_costs: list[float | None] = []

            with self._invoke_span(operation="stream", streaming=True) as invoke_span:
                for model_str, provider in self._models:
                    prompt_messages = self._build_messages(history, message)
                    try:
                        collected: list[str] = []
                        async for delta in self._stream_tool_loop(
                            agent_instance=agent_instance,
                            provider=provider,
                            model_str=model_str,
                            prompt_messages=prompt_messages,
                            wire_tools=wire_tools,
                            child_costs=child_costs,
                        ):
                            collected.append(delta)
                            yield delta
                    except LLMProviderError as exc:
                        last_error = exc
                        continue
                    await self._persist_turn(message, "".join(collected))
                    set_root_cost_total(invoke_span, child_costs)
                    return

                set_root_cost_total(invoke_span, child_costs)
                if self._fallback_callable is not None:
                    text = await self._run_callable_fallback(message)
                    yield text
                    return

                raise AgentProviderError(
                    f"Agent {self._agent_name!r} exhausted all providers"
                    f"{f' (last error: {last_error})' if last_error is not None else ''}."
                ) from last_error

        return _iterator()

    # ------------------------------------------------------------------
    # tool loop
    # ------------------------------------------------------------------

    async def _run_tool_loop(
        self,
        *,
        agent_instance: Any,
        provider: LLMProvider,
        model_str: str,
        prompt_messages: list[Message],
        wire_tools: list[Tool] | None,
        child_costs: list[float | None],
    ) -> str:
        """Drive the function-calling loop until a tool-free response.

        Mutates ``prompt_messages`` in place — appending the assistant's
        ``tool_use`` message and each ``tool_result`` per iteration — so a
        fallback retry starts from the original prompt list.
        """
        for iteration in range(self._max_tool_iterations + 1):
            response = await self._complete_with_span(
                provider=provider,
                model_str=model_str,
                prompt_messages=prompt_messages,
                wire_tools=wire_tools,
                child_costs=child_costs,
            )
            if not response.tool_calls:
                return response.text

            if iteration == self._max_tool_iterations:
                raise AgentToolLoopError(
                    f"Agent {self._agent_name!r} exceeded "
                    f"max_tool_iterations={self._max_tool_iterations}; "
                    f"the last response still requested "
                    f"{len(response.tool_calls)} tool call(s)."
                )

            prompt_messages.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            tool_results = await self._execute_tool_calls(
                agent_instance=agent_instance,
                tool_calls=response.tool_calls,
                iteration=iteration + 1,
            )
            prompt_messages.extend(tool_results)
        # Unreachable — the loop returns or raises in every iteration.
        raise AgentToolLoopError(f"Agent {self._agent_name!r} tool loop exited without a response.")

    async def _stream_tool_loop(
        self,
        *,
        agent_instance: Any,
        provider: LLMProvider,
        model_str: str,
        prompt_messages: list[Message],
        wire_tools: list[Tool] | None,
        child_costs: list[float | None],
    ) -> AsyncIterator[str]:
        """Stream text deltas, transparently handling tool-call rounds."""
        for iteration in range(self._max_tool_iterations + 1):
            text_parts: list[str] = []
            # index → {id, name, args_buffer}
            tool_accum: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None
            input_tokens = 0
            output_tokens = 0
            cache_creation = 0
            cache_read = 0
            terminal_usage: ChunkUsage | None = None

            with self._chat_span(provider=provider, model_str=model_str) as span:
                self._record_chat_request(span, prompt_messages=prompt_messages, streaming=True)
                try:
                    async for chunk in provider.stream(
                        model=model_str,
                        messages=prompt_messages,
                        tools=wire_tools,
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        cache=self._cache_prompt,
                    ):
                        if chunk.tool_call_delta is not None:
                            delta = chunk.tool_call_delta
                            key = delta.index if delta.index is not None else len(tool_accum)
                            entry = tool_accum.setdefault(key, {"id": "", "name": "", "args": ""})
                            if delta.id:
                                entry["id"] = delta.id
                            if delta.name:
                                entry["name"] = delta.name
                            if delta.arguments_delta:
                                entry["args"] += delta.arguments_delta
                        if chunk.delta:
                            text_parts.append(chunk.delta)
                            yield chunk.delta
                        if chunk.finish_reason is not None:
                            finish_reason = chunk.finish_reason
                        if chunk.usage is not None:
                            input_tokens = chunk.usage.input_tokens
                            output_tokens = chunk.usage.output_tokens
                            cache_creation = chunk.usage.cache_creation_input_tokens
                            cache_read = chunk.usage.cache_read_input_tokens
                            terminal_usage = chunk.usage
                except LLMProviderError as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                self._record_chat_response(
                    span,
                    text="".join(text_parts),
                    finish_reasons=[finish_reason] if finish_reason else [],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                cost = set_chat_cost_attrs(
                    span,
                    model=model_str,
                    usage=terminal_usage,
                    catalog=self._resolve_catalog(),
                )
                child_costs.append(cost)
                # Silence unused-name warnings while keeping the cache token
                # state available for future per-call logging.
                _ = (cache_creation, cache_read)

            if finish_reason != "tool_calls" or not tool_accum:
                return

            if iteration == self._max_tool_iterations:
                raise AgentToolLoopError(
                    f"Agent {self._agent_name!r} exceeded "
                    f"max_tool_iterations={self._max_tool_iterations} "
                    f"during streaming."
                )

            tool_calls = self._assemble_stream_tool_calls(tool_accum)
            prompt_messages.append(
                Message(
                    role="assistant",
                    content="".join(text_parts),
                    tool_calls=tool_calls,
                )
            )
            tool_results = await self._execute_tool_calls(
                agent_instance=agent_instance,
                tool_calls=tool_calls,
                iteration=iteration + 1,
            )
            prompt_messages.extend(tool_results)
        raise AgentToolLoopError(
            f"Agent {self._agent_name!r} stream tool loop exited without a response."
        )

    async def _complete_with_span(
        self,
        *,
        provider: LLMProvider,
        model_str: str,
        prompt_messages: list[Message],
        wire_tools: list[Tool] | None,
        child_costs: list[float | None],
    ) -> Response:
        with self._chat_span(provider=provider, model_str=model_str) as span:
            self._record_chat_request(span, prompt_messages=prompt_messages, streaming=False)
            try:
                response = await provider.complete(
                    model=model_str,
                    messages=prompt_messages,
                    tools=wire_tools,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    cache=self._cache_prompt,
                )
            except LLMProviderError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            self._record_chat_response(
                span,
                text=response.text,
                finish_reasons=[response.finish_reason],
                input_tokens=response.tokens_in,
                output_tokens=response.tokens_out,
            )
            cost = set_chat_cost_attrs(
                span,
                model=model_str,
                usage=response,
                catalog=self._resolve_catalog(),
            )
            child_costs.append(cost)
            return response

    def _resolve_catalog(self) -> Catalog:
        """Return the catalog to bill against on the next chat-span emission.

        Constructor-supplied ``catalog`` wins; otherwise we read the
        process-wide active catalog lazily — that way decorator-time
        construction never has to depend on the factory's
        ``pricing_overrides=`` plumbing (factory bootstrap runs *after*
        decoration).
        """
        if self._catalog is not None:
            return self._catalog
        return get_active_catalog()

    @staticmethod
    def _assemble_stream_tool_calls(accum: dict[int, dict[str, Any]]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for key in sorted(accum.keys()):
            entry = accum[key]
            args_raw = entry.get("args") or "{}"
            args: dict[str, Any] = {}
            if args_raw:
                try:
                    parsed: Any = json.loads(args_raw)
                except json.JSONDecodeError:
                    # Stream emitted malformed JSON; pass an empty dict and let
                    # the tool's schema validation surface the error to the LLM.
                    parsed = {}
                if isinstance(parsed, dict):
                    args = {str(k): v for k, v in parsed.items()}  # type: ignore[misc]
            calls.append(
                ToolCall(
                    id=entry.get("id") or f"call_{key}",
                    name=entry.get("name") or "",
                    arguments=args,
                )
            )
        return calls

    async def _execute_tool_calls(
        self,
        *,
        agent_instance: Any,
        tool_calls: list[ToolCall],
        iteration: int,
    ) -> list[Message]:
        """Dispatch each ``ToolCall`` and return one ``tool_result`` per call."""
        tasks = [
            self._execute_single_tool(
                agent_instance=agent_instance,
                call=call,
                iteration=iteration,
            )
            for call in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _execute_single_tool(
        self,
        *,
        agent_instance: Any,
        call: ToolCall,
        iteration: int,
    ) -> Message:
        binding = self._tool_by_name.get(call.name)
        if binding is None:
            return Message(
                role="tool",
                content=(
                    f"Unknown tool {call.name!r}. Available tools: {sorted(self._tool_by_name)}."
                ),
                tool_call_id=call.id,
                is_error=True,
            )

        with self._tool_span(call.name, call_id=call.id, iteration=iteration) as span:
            try:
                kwargs = binding.metadata.validate_arguments(call.arguments)
            except ValidationError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "invalid arguments"))
                return Message(
                    role="tool",
                    content=f"Invalid arguments for {call.name!r}: {exc}",
                    tool_call_id=call.id,
                    is_error=True,
                )

            owner = self._resolve_owner(agent_instance, binding)
            try:
                if binding.metadata.is_async:
                    result = await binding.metadata.fn(owner, **kwargs)
                else:
                    result = await asyncio.to_thread(binding.metadata.fn, owner, **kwargs)
            except Exception as exc:
                _LOGGER.warning(
                    "Tool %r on agent %r raised: %s",
                    call.name,
                    self._agent_name,
                    exc,
                )
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                return Message(
                    role="tool",
                    content=f"{type(exc).__name__}: {exc}",
                    tool_call_id=call.id,
                    is_error=True,
                )
            return Message(
                role="tool",
                content=_stringify_tool_result(result),
                tool_call_id=call.id,
            )

    def _resolve_owner(self, agent_instance: Any, binding: ToolBinding) -> Any:
        if binding.owner_cls is None:
            return agent_instance
        instance = self._extra_instances.get(binding.owner_cls)
        if instance is None:
            # discover_tools always populated the cache, so this is defensive.
            instance = binding.owner_cls()
            self._extra_instances[binding.owner_cls] = instance
        return instance

    # ------------------------------------------------------------------
    # span helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _invoke_span(self, *, operation: str, streaming: bool) -> Generator[Span]:
        with _TRACER.start_as_current_span(agent_invoke_span_name(self._agent_name)) as span:
            span.set_attribute(AJOLOPY_AGENT_NAME, self._agent_name)
            span.set_attribute(AJOLOPY_AGENT_OPERATION, operation)
            span.set_attribute(AJOLOPY_STREAMING, streaming)
            yield span

    @contextmanager
    def _chat_span(
        self,
        *,
        provider: LLMProvider,
        model_str: str,
    ) -> Generator[Span]:
        with _TRACER.start_as_current_span(chat_span_name(model_str)) as span:
            span.set_attribute(GEN_AI_SYSTEM, provider.gen_ai_system_for(model_str))
            span.set_attribute(GEN_AI_OPERATION_NAME, OPERATION_CHAT)
            span.set_attribute(GEN_AI_REQUEST_MODEL, model_str)
            if self._temperature is not None:
                span.set_attribute(GEN_AI_REQUEST_TEMPERATURE, self._temperature)
            if self._max_tokens is not None:
                span.set_attribute(GEN_AI_REQUEST_MAX_TOKENS, self._max_tokens)
            yield span

    @contextmanager
    def _tool_span(
        self,
        tool_name: str,
        *,
        call_id: str,
        iteration: int,
    ) -> Generator[Span]:
        with _TRACER.start_as_current_span(execute_tool_span_name(tool_name)) as span:
            span.set_attribute(GEN_AI_TOOL_NAME, tool_name)
            span.set_attribute(GEN_AI_TOOL_CALL_ID, call_id)
            span.set_attribute("ajolopy.tool.iteration", iteration)
            yield span

    @staticmethod
    def _record_chat_request(
        span: Span,
        *,
        prompt_messages: list[Message],
        streaming: bool,
    ) -> None:
        span.set_attribute(AJOLOPY_STREAMING, streaming)
        if is_content_capture_enabled():
            span.set_attribute(
                GEN_AI_PROMPT,
                json.dumps(
                    [{"role": m.role, "content": m.content} for m in prompt_messages],
                    ensure_ascii=False,
                ),
            )

    @staticmethod
    def _record_chat_response(
        span: Span,
        *,
        text: str,
        finish_reasons: list[str | None],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        reasons = [r for r in finish_reasons if r]
        if reasons:
            span.set_attribute(GEN_AI_RESPONSE_FINISH_REASONS, reasons)
        if input_tokens > 0:
            span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, input_tokens)
        if output_tokens > 0:
            span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)
        if is_content_capture_enabled() and text:
            span.set_attribute(GEN_AI_COMPLETION, text)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _load_history(self) -> list[Message]:
        if self._memory is None:
            return []
        return await self._memory.get(_DEFAULT_SESSION_ID)

    def _build_messages(self, history: list[Message], user_message: str) -> list[Message]:
        messages: list[Message] = []
        system_text = self._system(user_message) if callable(self._system) else self._system
        messages.append(Message(role="system", content=system_text))
        messages.extend(history)
        messages.append(Message(role="user", content=user_message))
        return messages

    async def _persist_turn(self, user_message: str, assistant_text: str) -> None:
        if self._memory is None:
            return
        await self._memory.append(_DEFAULT_SESSION_ID, Message(role="user", content=user_message))
        await self._memory.append(
            _DEFAULT_SESSION_ID, Message(role="assistant", content=assistant_text)
        )

    async def _run_callable_fallback(self, message: str) -> str:
        fallback = self._fallback_callable
        if fallback is None:
            raise AgentError(f"Agent {self._agent_name!r} has no callable fallback configured.")
        try:
            result = fallback(message)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentError(f"Agent {self._agent_name!r} callable fallback raised: {exc}") from exc
        if not isinstance(result, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise AgentError(
                f"Agent {self._agent_name!r} callable fallback must return a "
                f"string, got {type(result).__name__}."
            )
        return result

    # Exposed for tests so they can inspect the bindings without touching
    # the private attribute directly.
    @property
    def tool_names(self) -> list[str]:
        return [b.metadata.name for b in self._tool_bindings]


def _stringify_tool_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except TypeError, ValueError:
        return str(value)


__all__ = [
    "AgentRuntime",
    "FallbackSpec",
    "Response",
    "SystemPrompt",
]
