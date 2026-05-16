"""Tests for ``set_chat_cost_attrs`` — the chat-span emission path.

Exercises both non-streaming (``Response``) and streaming
(``ChunkUsage``) sources end-to-end through ``AgentRuntime`` so the
five ``gen_ai.cost_usd*`` attrs land on the OTel chat span via the
``InMemorySpanExporter`` already wired up in ``conftest.py``.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any, override

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.observability import Catalog, ModelPrice
from ajolopy.observability.pricing import set_default_catalog
from ajolopy.providers import Chunk, ChunkUsage, Response, register_provider
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


@pytest.fixture
def reset_active_catalog() -> Iterator[None]:
    """Snapshot + restore the process-wide active catalog around each test."""
    try:
        yield
    finally:
        set_default_catalog(None)


@pytest.fixture
def sonnet_catalog() -> Catalog:
    return Catalog(
        {
            "claude-opus-4-7": ModelPrice(
                input_cost_per_token=3e-6,
                output_cost_per_token=15e-6,
                cache_creation_input_token_cost=3.75e-6,
                cache_read_input_token_cost=3e-7,
            )
        }
    )


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


class _CacheUsageFake(FakeProvider):
    """Fake provider whose default Response carries cache-tier counts."""

    GEN_AI_SYSTEM = "anthropic"

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        await super().complete(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
        )
        return Response(
            text="hi",
            tokens_in=1000,
            tokens_out=500,
            cache_creation_input_tokens=200,
            cache_read_input_tokens=300,
            finish_reason="stop",
        )


@pytest.mark.asyncio
async def test_chat_span_gets_five_cost_attrs_for_known_model(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    sonnet_catalog: Catalog,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(sonnet_catalog)
    register_provider("anthropic", _CacheUsageFake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert attrs["gen_ai.cost_usd"] == pytest.approx(
        1000 * 3e-6 + 500 * 15e-6 + 200 * 3.75e-6 + 300 * 3e-7
    )
    assert attrs["gen_ai.cost_usd.input"] == pytest.approx(1000 * 3e-6)
    assert attrs["gen_ai.cost_usd.output"] == pytest.approx(500 * 15e-6)
    assert attrs["gen_ai.cost_usd.cache_creation"] == pytest.approx(200 * 3.75e-6)
    assert attrs["gen_ai.cost_usd.cache_read"] == pytest.approx(300 * 3e-7)


class _StreamingCacheFake(FakeProvider):
    GEN_AI_SYSTEM = "anthropic"

    @override
    def stream(
        self,
        *,
        model: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:

        async def _it() -> AsyncIterator[Chunk]:
            yield Chunk(delta="he")
            yield Chunk(delta="llo")
            yield Chunk(
                delta="",
                finish_reason="stop",
                usage=ChunkUsage(
                    input_tokens=1000,
                    output_tokens=500,
                    cache_creation_input_tokens=200,
                    cache_read_input_tokens=300,
                ),
            )

        return _it()


@pytest.mark.asyncio
async def test_streaming_chat_span_gets_five_cost_attrs(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    sonnet_catalog: Catalog,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(sonnet_catalog)
    register_provider("anthropic", _StreamingCacheFake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    out: list[str] = []
    async for delta in Demo().stream("hi"):  # type: ignore[attr-defined]
        out.append(delta)
    assert "".join(out) == "hello"

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert attrs["gen_ai.cost_usd"] == pytest.approx(
        1000 * 3e-6 + 500 * 15e-6 + 200 * 3.75e-6 + 300 * 3e-7
    )
    assert attrs["gen_ai.cost_usd.input"] == pytest.approx(1000 * 3e-6)
    assert attrs["gen_ai.cost_usd.output"] == pytest.approx(500 * 15e-6)
    assert attrs["gen_ai.cost_usd.cache_creation"] == pytest.approx(200 * 3.75e-6)
    assert attrs["gen_ai.cost_usd.cache_read"] == pytest.approx(300 * 3e-7)


@pytest.mark.asyncio
async def test_unknown_model_omits_cost_attrs(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(Catalog({}))  # empty — every model is unknown
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]
    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert "gen_ai.cost_usd" not in attrs
    assert "gen_ai.cost_usd.input" not in attrs
    assert "gen_ai.cost_usd.output" not in attrs
    assert "gen_ai.cost_usd.cache_creation" not in attrs
    assert "gen_ai.cost_usd.cache_read" not in attrs


@pytest.mark.asyncio
async def test_streaming_without_usage_omits_cost_attrs(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    sonnet_catalog: Catalog,
) -> None:
    """Some upstreams stream no terminal usage chunk — the span must not
    emit cost attrs in that case, even when the model is known."""
    _ = reset_active_catalog
    set_default_catalog(sonnet_catalog)

    class _NoUsageStreamFake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

        @override
        def stream(
            self,
            *,
            model: str,
            messages: list[Any],
            tools: list[Any] | None = None,
            temperature: float | None = None,
            max_tokens: int | None = None,
            cache: bool = False,
        ) -> AsyncIterator[Chunk]:

            async def _it() -> AsyncIterator[Chunk]:
                yield Chunk(delta="hi", finish_reason="stop")

            return _it()

    register_provider("anthropic", _NoUsageStreamFake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    out: list[str] = []
    async for delta in Demo().stream("ping"):  # type: ignore[attr-defined]
        out.append(delta)

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert "gen_ai.cost_usd" not in attrs
