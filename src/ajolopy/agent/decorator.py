"""``@Agent`` class decorator.

Decorates a Python class with an ``AgentRuntime`` and injects ``run`` /
``stream`` instance methods that delegate to it. The runtime is built and
validated at decoration time so misconfigured agents fail at import / boot,
not at first request.
"""

from typing import TYPE_CHECKING, Any, Literal, TypeVar

from .runtime import AgentRuntime, FallbackSpec, SystemPrompt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

T = TypeVar("T")


def Agent(  # noqa: N802 — public surface mirrors the Brief's primitive name.
    *,
    model: str,
    system: SystemPrompt,
    memory: object = None,
    trace: bool = False,
    cache: Literal["prompt"] | None = None,
    fallback: FallbackSpec = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[type[Any]] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Class decorator factory — see ``specs/agent.md`` for the full surface."""

    def _decorate(cls: type[T]) -> type[T]:
        runtime = AgentRuntime(
            agent_name=cls.__name__,
            model=model,
            system=system,
            memory=memory,
            trace_enabled=trace,
            cache=cache,
            fallback=fallback,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )

        async def run(self: T, message: str) -> str:  # noqa: ARG001 — self only used for binding.
            return await runtime.run(message)

        def stream(self: T, message: str) -> AsyncIterator[str]:  # noqa: ARG001
            return runtime.stream(message)

        cls._agent_runtime = runtime  # type: ignore[attr-defined]
        cls.run = run  # type: ignore[attr-defined]
        cls.stream = stream  # type: ignore[attr-defined]
        return cls

    return _decorate
