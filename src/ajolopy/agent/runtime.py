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
"""

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from opentelemetry import trace
from pydantic import ValidationError

from ajolopy.memory import Memory, resolve_memory
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

_TRACER = trace.get_tracer("ajolopy.agent")
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
        trace_enabled: bool,
        cache: Literal["prompt"] | None,
        fallback: FallbackSpec,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[type[Any]] | None,
        max_tool_iterations: int,
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
        self._trace_enabled = trace_enabled
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

        for model_str, provider in self._models:
            with self._span("run", model=model_str, provider_cls=type(provider)):
                try:
                    final_text = await self._run_tool_loop(
                        agent_instance=agent_instance,
                        provider=provider,
                        model_str=model_str,
                        prompt_messages=prompt_messages,
                        wire_tools=wire_tools,
                    )
                except LLMProviderError as exc:
                    last_error = exc
                    # Reset the message buffer between fallback attempts so a
                    # half-finished tool loop doesn't leak into the next try.
                    prompt_messages = self._build_messages(history, message)
                    continue
                await self._persist_turn(message, final_text)
                return final_text

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

            for model_str, provider in self._models:
                prompt_messages = self._build_messages(history, message)
                with self._span("stream", model=model_str, provider_cls=type(provider)):
                    try:
                        collected: list[str] = []
                        async for delta in self._stream_tool_loop(
                            agent_instance=agent_instance,
                            provider=provider,
                            model_str=model_str,
                            prompt_messages=prompt_messages,
                            wire_tools=wire_tools,
                        ):
                            collected.append(delta)
                            yield delta
                    except LLMProviderError as exc:
                        last_error = exc
                        continue
                    await self._persist_turn(message, "".join(collected))
                    return

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
    ) -> str:
        """Drive the function-calling loop until a tool-free response.

        Mutates ``prompt_messages`` in place — appending the assistant's
        ``tool_use`` message and each ``tool_result`` per iteration — so a
        fallback retry starts from the original prompt list.
        """
        for iteration in range(self._max_tool_iterations + 1):
            response = await provider.complete(
                model=model_str,
                messages=prompt_messages,
                tools=wire_tools,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                cache=self._cache_prompt,
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
    ) -> AsyncIterator[str]:
        """Stream text deltas, transparently handling tool-call rounds."""
        for iteration in range(self._max_tool_iterations + 1):
            text_parts: list[str] = []
            # index → {id, name, args_buffer}
            tool_accum: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None

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

        with self._tool_span(binding.metadata.name, iteration=iteration) as span:
            try:
                kwargs = binding.metadata.validate_arguments(call.arguments)
            except ValidationError as exc:
                _set_attr(span, "tool.success", False)
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
                _set_attr(span, "tool.success", False)
                return Message(
                    role="tool",
                    content=f"{type(exc).__name__}: {exc}",
                    tool_call_id=call.id,
                    is_error=True,
                )
            _set_attr(span, "tool.success", True)
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

    def _span(self, op: str, *, model: str, provider_cls: type[LLMProvider]) -> Any:
        if not self._trace_enabled:
            return _NULL_SPAN
        span = _TRACER.start_as_current_span(f"agent.{op}")
        return _SpanAttrs(span, agent_name=self._agent_name, model=model, provider_cls=provider_cls)

    def _tool_span(self, tool_name: str, *, iteration: int) -> Any:
        if not self._trace_enabled:
            return _NULL_SPAN
        span = _TRACER.start_as_current_span("agent.tool")
        return _ToolSpanAttrs(span, tool_name=tool_name, iteration=iteration)

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


def _set_attr(span_ctx: Any, key: str, value: Any) -> None:
    """Best-effort attribute setter that tolerates the no-op null span."""
    setter = getattr(span_ctx, "set_attribute", None)
    if callable(setter):
        setter(key, value)


# We need a small thin adapter so the tool span can also record attributes
# from the body of the `with` block (success/failure). The base
# `_SpanAttrs` only sets attrs on enter.
class _ToolSpanAttrs:
    def __init__(self, ctx: Any, *, tool_name: str, iteration: int) -> None:
        self._ctx = ctx
        self._tool_name = tool_name
        self._iteration = iteration
        self._span: Any = None

    def __enter__(self) -> _ToolSpanAttrs:
        self._span = self._ctx.__enter__()
        self._span.set_attribute("tool.name", self._tool_name)
        self._span.set_attribute("tool.iteration", self._iteration)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        return self._ctx.__exit__(exc_type, exc, tb)

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is not None:
            self._span.set_attribute(key, value)


class _SpanAttrs:
    """Context manager that sets standard agent.* attributes on its span."""

    def __init__(
        self,
        ctx: Any,
        *,
        agent_name: str,
        model: str,
        provider_cls: type[LLMProvider],
    ) -> None:
        self._ctx = ctx
        self._agent_name = agent_name
        self._model = model
        self._provider_cls = provider_cls

    def __enter__(self) -> None:
        span = self._ctx.__enter__()
        span.set_attribute("agent.name", self._agent_name)
        span.set_attribute("agent.model", self._model)
        span.set_attribute("agent.provider", self._provider_cls.__module__)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        return self._ctx.__exit__(exc_type, exc, tb)


class _NullSpan:
    """No-op context manager used when ``trace=False``."""

    def __enter__(self) -> _NullSpan:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def set_attribute(self, _key: str, _value: Any) -> None:
        return None


_NULL_SPAN = _NullSpan()


__all__ = [
    "AgentRuntime",
    "FallbackSpec",
    "Response",
    "SystemPrompt",
]
