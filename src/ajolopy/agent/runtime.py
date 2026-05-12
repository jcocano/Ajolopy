"""``AgentRuntime`` — the run/stream engine behind the ``@Agent`` decorator.

The decorator builds one ``AgentRuntime`` per decorated class at decoration
time and binds it to the class. Instance methods ``run`` / ``stream`` close
over the runtime so per-instance state stays at the class level (the agent
config is shared across instances by design).
"""

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import trace

from ajolopy.memory import Memory, resolve_memory
from ajolopy.providers import (
    LLMProvider,
    LLMProviderError,
    Message,
    ProviderNotRegisteredError,
    UnknownModelError,
    get_provider_class,
    resolve_provider,
)

from .errors import (
    AgentConfigError,
    AgentError,
    AgentProviderError,
    AgentToolUseUnsupportedError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_TRACER = trace.get_tracer("ajolopy.agent")

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
        agent_name: str,
        model: str,
        system: SystemPrompt,
        memory: object,
        trace_enabled: bool,
        cache: Literal["prompt"] | None,
        fallback: FallbackSpec,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[type[Any]] | None,
    ) -> None:
        if cache == "prompt" and callable(system):
            raise AgentConfigError(
                "cache='prompt' requires a static system prompt; a callable "
                "system prompt cannot be safely cached. Either drop cache or "
                "make the system kwarg a string."
            )

        self._agent_name = agent_name
        self._system: SystemPrompt = system
        self._trace_enabled = trace_enabled
        self._cache_prompt = cache == "prompt"
        self._temperature = temperature
        self._max_tokens = max_tokens
        # Tool discovery is in scope for AJ-1; passing tools to the model and
        # executing the function-calling loop lives in AJ-2.
        self._tools = tools or []

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

    async def run(self, message: str) -> str:
        history = await self._load_history()
        prompt_messages = self._build_messages(history, message)
        last_error: BaseException | None = None

        for model_str, provider in self._models:
            with self._span("run", model=model_str, provider_cls=type(provider)):
                try:
                    response = await provider.complete(
                        model=model_str,
                        messages=prompt_messages,
                        tools=None,  # AJ-2 wires tools end-to-end
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        cache=self._cache_prompt,
                    )
                except LLMProviderError as exc:
                    last_error = exc
                    continue
                if response.tool_calls:
                    raise AgentToolUseUnsupportedError(
                        f"Agent {self._agent_name!r} received a tool_use "
                        f"response but the tool-calling loop ships in AJ-2."
                    )
                await self._persist_turn(message, response.text)
                return response.text

        # All providers failed. Try the callable fallback if present.
        if self._fallback_callable is not None:
            return await self._run_callable_fallback(message)

        raise AgentProviderError(
            f"Agent {self._agent_name!r} exhausted all providers"
            f"{f' (last error: {last_error})' if last_error is not None else ''}."
        ) from last_error

    def stream(self, message: str) -> AsyncIterator[str]:
        async def _iterator() -> AsyncIterator[str]:
            history = await self._load_history()
            prompt_messages = self._build_messages(history, message)
            last_error: BaseException | None = None
            collected_text: list[str] = []

            for model_str, provider in self._models:
                with self._span("stream", model=model_str, provider_cls=type(provider)):
                    try:
                        async for chunk in provider.stream(
                            model=model_str,
                            messages=prompt_messages,
                            tools=None,
                            temperature=self._temperature,
                            max_tokens=self._max_tokens,
                            cache=self._cache_prompt,
                        ):
                            if chunk.tool_call_delta is not None:
                                raise AgentToolUseUnsupportedError(
                                    f"Agent {self._agent_name!r} received a "
                                    f"tool_use stream event; the tool loop ships "
                                    f"in AJ-2."
                                )
                            if chunk.delta:
                                collected_text.append(chunk.delta)
                                yield chunk.delta
                    except LLMProviderError as exc:
                        last_error = exc
                        collected_text.clear()
                        continue
                    await self._persist_turn(message, "".join(collected_text))
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
    # helpers
    # ------------------------------------------------------------------

    async def _load_history(self) -> list[Message]:
        if self._memory is None:
            return []
        return await self._memory.get(_DEFAULT_SESSION_ID)

    def _build_messages(self, history: list[Message], user_message: str) -> list[Message]:
        messages: list[Message] = []
        # ``system`` is either a static string or a per-request callable.
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
        # Defensive: callers can pass any callable, signature is untyped.
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
        # ``start_as_current_span`` returns a context manager. We wrap it
        # in a thin adapter that sets the attributes once entered.
        return _SpanAttrs(span, agent_name=self._agent_name, model=model, provider_cls=provider_cls)


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

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> bool:
        return False


_NULL_SPAN = _NullSpan()
