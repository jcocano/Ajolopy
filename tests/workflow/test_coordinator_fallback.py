"""Tests for ``@Workflow(coordinator_fallback=[...])`` (AJ-23).

Mirrors :mod:`tests.agent.test_fallback_observability`: validates the
decoration-time contract (unknown model in chain raises
:class:`WorkflowConfigError`, structural checks, the route-override
hedge) and the runtime contract (coordinator chat falling through the
chain emits one ``gen_ai.chat.fallback`` event per transition on the
chat span that eventually responds).
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any, override

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent, Workflow
from ajolopy.observability.conventions import (
    AJOLOPY_FALLBACK_FROM,
    AJOLOPY_FALLBACK_FROM_PROVIDER,
    AJOLOPY_FALLBACK_TO,
    AJOLOPY_FALLBACK_TO_PROVIDER,
    GEN_AI_CHAT_FALLBACK_EVENT,
)
from ajolopy.providers import (
    Chunk,
    LLMProviderError,
    Message,
    Tool,
    register_provider,
)
from ajolopy.workflow import WorkflowConfigError, WorkflowError
from tests.agent.conftest import FakeProvider
from tests.observability.conftest import ensure_session_provider
from tests.workflow.conftest import ScriptedStreamProvider


@pytest.fixture
def tracer_provider() -> Iterator[InMemorySpanExporter]:
    exporter = ensure_session_provider()
    exporter.clear()
    try:
        yield exporter
    finally:
        exporter.clear()


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _register_anthropic() -> None:
    register_provider("anthropic", ScriptedStreamProvider, overwrite=True)


# ---------------------------------------------------------------------------
# Decoration-time validation
# ---------------------------------------------------------------------------


def test_unknown_model_in_fallback_chain_raises_at_decoration() -> None:
    _register_anthropic()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    with pytest.raises(WorkflowConfigError, match="totally-unknown"):

        @Workflow(
            coordinator="claude-sonnet-4-7",
            coordinator_fallback=["totally-unknown"],
            agents=[Spec],
        )
        class _Team:
            pass


def test_non_list_coordinator_fallback_raises() -> None:
    _register_anthropic()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    with pytest.raises(WorkflowConfigError, match="list of model strings"):

        @Workflow(
            coordinator="claude-sonnet-4-7",
            coordinator_fallback="claude-haiku-4-5",  # type: ignore[arg-type]
            agents=[Spec],
        )
        class _Team:
            pass


def test_non_string_entry_in_coordinator_fallback_raises() -> None:
    _register_anthropic()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    with pytest.raises(WorkflowConfigError, match="model strings"):

        @Workflow(
            coordinator="claude-sonnet-4-7",
            coordinator_fallback=[123],  # type: ignore[list-item]
            agents=[Spec],
        )
        class _Team:
            pass


def test_coordinator_fallback_ignored_when_route_overrides() -> None:
    _register_anthropic()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    @Workflow(
        coordinator="claude-sonnet-4-7",
        coordinator_fallback=["claude-haiku-4-5"],
        agents=[Spec],
    )
    class Team:
        async def route(self, message: str, context: dict[str, Any]) -> type[Any]:
            _ = (message, context)
            return Spec

    runtime = Team._workflow_runtime  # type: ignore[attr-defined]
    # When route() wins, no coordinator chain is resolved — empty list and
    # no provider instances are wired.
    assert runtime._coordinator_models == []
    assert runtime._coordinator_provider is None


# ---------------------------------------------------------------------------
# Runtime fallback in the coordinator
# ---------------------------------------------------------------------------


class _FailFirstStream(ScriptedStreamProvider):
    """ScriptedStreamProvider that raises on the FIRST stream call only."""

    GEN_AI_SYSTEM = "anthropic"
    fail_calls: int = 1

    def __init__(self) -> None:
        super().__init__()
        self._stream_invocations = 0

    @override
    def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:
        self._stream_invocations += 1
        attempt = self._stream_invocations
        max_fails = type(self).fail_calls
        # Capture call details for assertions even on failed attempts.
        self.stream_calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "cache": cache,
            }
        )
        round_index = self._round_index
        if attempt > max_fails and round_index < len(self.stream_rounds):
            events = self.stream_rounds[round_index]
            self._round_index += 1
        else:
            events = [Chunk(delta="ok", finish_reason="stop")]

        async def _it() -> AsyncIterator[Chunk]:
            if attempt <= max_fails:
                raise LLMProviderError(f"coordinator fail {attempt}")
            for event in events:
                yield event

        return _it()


@pytest.mark.asyncio
async def test_coordinator_fallback_advances_through_chain_and_emits_event(
    tracer_provider: InMemorySpanExporter,
) -> None:
    class _Provider(_FailFirstStream):
        fail_calls = 1

    register_provider("anthropic", _Provider, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    @Workflow(
        coordinator="claude-sonnet-4-7",
        coordinator_fallback=["claude-haiku-4-5"],
        agents=[Spec],
    )
    class Team:
        pass

    coordinator_provider: _Provider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator_provider.stream_rounds = [
        [Chunk(delta="all good", finish_reason="stop")],
    ]

    result = await Team().run("hi")  # type: ignore[attr-defined]
    assert result == "all good"

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    assert {s.name for s in chat_spans} == {
        "chat claude-sonnet-4-7",
        "chat claude-haiku-4-5",
    }
    fallback_span = next(s for s in chat_spans if s.name == "chat claude-haiku-4-5")
    events = [e for e in fallback_span.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert len(events) == 1
    attrs = dict(events[0].attributes or {})
    assert attrs[AJOLOPY_FALLBACK_FROM] == "claude-sonnet-4-7"
    assert attrs[AJOLOPY_FALLBACK_FROM_PROVIDER] == "anthropic"
    assert attrs[AJOLOPY_FALLBACK_TO] == "claude-haiku-4-5"
    assert attrs[AJOLOPY_FALLBACK_TO_PROVIDER] == "anthropic"


@pytest.mark.asyncio
async def test_exhausting_coordinator_chain_raises_workflow_error() -> None:
    """When the configured chain is fully consumed, surface a WorkflowError."""

    class _AlwaysFail(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

        @override
        def stream(
            self,
            *,
            model: str,
            messages: list[Message],
            tools: list[Tool] | None = None,
            temperature: float | None = None,
            max_tokens: int | None = None,
            cache: bool = False,
        ) -> AsyncIterator[Chunk]:
            self.stream_calls.append(
                {
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "cache": cache,
                }
            )

            async def _it() -> AsyncIterator[Chunk]:
                raise LLMProviderError(f"down: {model}")
                yield  # pragma: no cover - unreachable

            return _it()

    register_provider("anthropic", _AlwaysFail, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    @Workflow(
        coordinator="claude-sonnet-4-7",
        coordinator_fallback=["claude-haiku-4-5"],
        agents=[Spec],
    )
    class Team:
        pass

    with pytest.raises(WorkflowError, match="exhausted all coordinator"):
        await Team().run("hi")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_coordinator_provider_cache_reuses_instance_per_provider_key() -> None:
    """All chain entries pointing at the same provider key share one instance."""

    _register_anthropic()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Spec:
        """Specialist."""

    @Workflow(
        coordinator="claude-sonnet-4-7",
        coordinator_fallback=["claude-opus-4-1", "claude-haiku-4-5"],
        agents=[Spec],
    )
    class Team:
        pass

    runtime = Team._workflow_runtime  # type: ignore[attr-defined]
    providers = [entry[1] for entry in runtime._coordinator_models]
    assert len(providers) == 3
    # Three Anthropic-routed models → one shared provider instance.
    assert providers[0] is providers[1] is providers[2]
