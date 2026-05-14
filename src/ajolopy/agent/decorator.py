"""``@Agent`` class decorator.

Decorates a Python class with an ``AgentRuntime`` and injects ``run`` /
``stream`` instance methods that delegate to it. The runtime is built and
validated at decoration time so misconfigured agents fail at import / boot,
not at first request.
"""

from typing import TYPE_CHECKING, Any, Literal

from .runtime import AgentRuntime

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from .runtime import FallbackSpec, SystemPrompt

_DEFAULT_MAX_TOOL_ITERATIONS = 10


def Agent[T](  # noqa: N802 — public surface mirrors the Brief's primitive name.
    *,
    model: str,
    system: SystemPrompt,
    memory: object = None,
    cache: Literal["prompt"] | None = None,
    fallback: FallbackSpec = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[type[Any]] | None = None,
    max_tool_iterations: int = _DEFAULT_MAX_TOOL_ITERATIONS,
) -> Callable[[type[T]], type[T]]:
    """Class decorator factory — see ``specs/agent.md`` for the full surface.

    OpenTelemetry instrumentation is always on. Spans flow through the
    ``opentelemetry-api`` tracer; without an SDK (``ajolopy[otel]`` extra) the
    spans are cheap no-ops. The previous ``trace=True`` kwarg has been
    removed: per-primitive gating broke composition with ``@Workflow`` /
    ``@MCP``. Backend selection happens at the SDK layer via standard OTel
    env vars (``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``).
    """

    def _decorate(cls: type[T]) -> type[T]:
        runtime = AgentRuntime(
            agent_cls=cls,
            model=model,
            system=system,
            memory=memory,
            cache=cache,
            fallback=fallback,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            max_tool_iterations=max_tool_iterations,
        )

        async def run(self: T, message: str) -> str:
            return await runtime.run(self, message)

        def stream(self: T, message: str) -> AsyncIterator[str]:
            return runtime.stream(self, message)

        cls._agent_runtime = runtime  # type: ignore[attr-defined]
        cls.run = run  # type: ignore[attr-defined]
        cls.stream = stream  # type: ignore[attr-defined]
        return cls

    return _decorate
