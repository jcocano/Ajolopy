"""Observability tests for the ``@Agent`` fallback chain (AJ-23).

Asserts the ``gen_ai.chat.fallback`` span event shape produced by
:class:`ajolopy.agent.runtime.AgentRuntime` when one or more provider
calls raise :class:`LLMProviderError` before a downstream model
eventually responds. Mirrors the existing ``tests/observability``
patterns: a shared ``InMemorySpanExporter`` captures the spans, and a
fake provider matrix forces deterministic failure / success transitions.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any, override

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.observability.conventions import (
    AJOLOPY_FALLBACK_FROM,
    AJOLOPY_FALLBACK_FROM_PROVIDER,
    AJOLOPY_FALLBACK_REASON,
    AJOLOPY_FALLBACK_TO,
    AJOLOPY_FALLBACK_TO_PROVIDER,
    FALLBACK_REASON_MAX_CHARS,
    GEN_AI_CHAT_FALLBACK_EVENT,
)
from ajolopy.providers import (
    Chunk,
    LLMProviderError,
    Message,
    Response,
    Tool,
    register_provider,
)
from tests.agent.conftest import FakeProvider
from tests.observability.conftest import ensure_session_provider


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


class _FailUntil(FakeProvider):
    """Fake provider that fails on the first ``fail_count`` complete calls."""

    GEN_AI_SYSTEM = "anthropic"
    fail_count: int = 1

    def __init__(self) -> None:
        super().__init__()
        self._calls = 0

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        self._calls += 1
        if self._calls <= type(self).fail_count:
            raise LLMProviderError(f"transient on attempt {self._calls}")
        return Response(text=f"answered by {model}", tokens_in=1, tokens_out=1)


@pytest.mark.asyncio
async def test_single_fallback_emits_one_event_on_secondary_chat_span(
    tracer_provider: InMemorySpanExporter,
) -> None:
    class _Provider(_FailUntil):
        fail_count = 1

    register_provider("anthropic", _Provider, overwrite=True)

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback="claude-haiku-4-5",
    )
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    assert len(chat_spans) == 2
    primary = next(s for s in chat_spans if s.name == "chat claude-sonnet-4-7")
    secondary = next(s for s in chat_spans if s.name == "chat claude-haiku-4-5")

    primary_events = [e for e in primary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    secondary_events = [e for e in secondary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert primary_events == []
    assert len(secondary_events) == 1
    attrs = dict(secondary_events[0].attributes or {})
    assert attrs[AJOLOPY_FALLBACK_FROM] == "claude-sonnet-4-7"
    assert attrs[AJOLOPY_FALLBACK_FROM_PROVIDER] == "anthropic"
    assert attrs[AJOLOPY_FALLBACK_TO] == "claude-haiku-4-5"
    assert attrs[AJOLOPY_FALLBACK_TO_PROVIDER] == "anthropic"
    assert "transient on attempt 1" in str(attrs[AJOLOPY_FALLBACK_REASON])


@pytest.mark.asyncio
async def test_double_fallback_emits_two_events_on_tertiary_chat_span(
    tracer_provider: InMemorySpanExporter,
) -> None:
    class _Provider(_FailUntil):
        fail_count = 2

    register_provider("anthropic", _Provider, overwrite=True)

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback=["claude-opus-4-1", "claude-haiku-4-5"],
    )
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    assert {s.name for s in chat_spans} == {
        "chat claude-sonnet-4-7",
        "chat claude-opus-4-1",
        "chat claude-haiku-4-5",
    }
    tertiary = next(s for s in chat_spans if s.name == "chat claude-haiku-4-5")
    secondary = next(s for s in chat_spans if s.name == "chat claude-opus-4-1")
    primary = next(s for s in chat_spans if s.name == "chat claude-sonnet-4-7")

    # Per spec: both transitions land on the tertiary's chat span (the
    # first chat span that actually responded).
    primary_events = [e for e in primary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    secondary_events = [e for e in secondary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    tertiary_events = [e for e in tertiary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert primary_events == []
    assert secondary_events == []
    assert len(tertiary_events) == 2

    first_attrs = dict(tertiary_events[0].attributes or {})
    second_attrs = dict(tertiary_events[1].attributes or {})
    assert first_attrs[AJOLOPY_FALLBACK_FROM] == "claude-sonnet-4-7"
    assert first_attrs[AJOLOPY_FALLBACK_TO] == "claude-opus-4-1"
    assert second_attrs[AJOLOPY_FALLBACK_FROM] == "claude-opus-4-1"
    assert second_attrs[AJOLOPY_FALLBACK_TO] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_reason_attribute_truncated_to_200_chars(
    tracer_provider: InMemorySpanExporter,
) -> None:
    huge_reason = "x" * 1000

    class _Provider(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

        def __init__(self) -> None:
            super().__init__()
            self._calls = 0

        @override
        async def complete(
            self,
            *,
            model: str,
            messages: list[Message],
            tools: list[Tool] | None = None,
            temperature: float | None = None,
            max_tokens: int | None = None,
            cache: bool = False,
        ) -> Response:
            self._calls += 1
            if self._calls == 1:
                raise LLMProviderError(huge_reason)
            return Response(text=f"ok via {model}", tokens_in=1, tokens_out=1)

    register_provider("anthropic", _Provider, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…", fallback="claude-haiku-4-5")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    secondary = next(s for s in chat_spans if s.name == "chat claude-haiku-4-5")
    events = [e for e in secondary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert len(events) == 1
    reason = str((events[0].attributes or {})[AJOLOPY_FALLBACK_REASON])
    assert len(reason) == FALLBACK_REASON_MAX_CHARS
    assert reason == "x" * FALLBACK_REASON_MAX_CHARS


@pytest.mark.asyncio
async def test_successful_primary_emits_no_fallback_events(
    register_fake_anthropic: type[FakeProvider],
    tracer_provider: InMemorySpanExporter,
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…", fallback="claude-haiku-4-5")
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    assert len(chat_spans) == 1
    events = [e for s in chat_spans for e in s.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert events == []


class _StreamFailUntil(FakeProvider):
    """Fake provider whose ``stream`` fails on the first ``fail_count`` calls."""

    GEN_AI_SYSTEM = "anthropic"
    fail_count: int = 1

    def __init__(self) -> None:
        super().__init__()
        self._calls = 0

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
        self._calls += 1
        attempt = self._calls
        max_fails = type(self).fail_count

        async def _it() -> AsyncIterator[Chunk]:
            if attempt <= max_fails:
                raise LLMProviderError(f"stream fail {attempt}")
            yield Chunk(delta=f"reply from {model}")
            yield Chunk(delta="", finish_reason="stop")

        return _it()


@pytest.mark.asyncio
async def test_stream_path_emits_fallback_event(
    tracer_provider: InMemorySpanExporter,
) -> None:
    class _Provider(_StreamFailUntil):
        fail_count = 1

    register_provider("anthropic", _Provider, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…", fallback="claude-haiku-4-5")
    class Demo:
        pass

    collected: list[str] = []
    async for delta in Demo().stream("hello"):  # type: ignore[attr-defined]
        collected.append(delta)
    assert "claude-haiku-4-5" in "".join(collected)

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    secondary = next(s for s in chat_spans if s.name == "chat claude-haiku-4-5")
    events = [e for e in secondary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert len(events) == 1
    attrs: dict[str, Any] = dict(events[0].attributes or {})
    assert attrs[AJOLOPY_FALLBACK_FROM] == "claude-sonnet-4-7"
    assert attrs[AJOLOPY_FALLBACK_TO] == "claude-haiku-4-5"
