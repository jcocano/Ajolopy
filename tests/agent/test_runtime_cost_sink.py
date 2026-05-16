"""Tests for the private ``cost_sink`` kwarg on ``AgentRuntime.run/stream``.

The kwarg is the orchestrator hook the ``@Workflow`` runtime uses to roll
the cost of each delegated agent's chat spans up into the workflow's own
``ajolopy.cost_usd.total`` attribute. It is not part of the public surface
(``Cls().run("...")`` does not expose it); these tests lock the contract
so future refactors do not silently drop or alter it.
"""

from collections.abc import Iterator

import pytest
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
    try:
        yield
    finally:
        set_default_catalog(None)


@pytest.fixture
def billable_catalog() -> Catalog:
    return Catalog(
        {
            "claude-opus-4-7": ModelPrice(
                input_cost_per_token=3e-6,
                output_cost_per_token=15e-6,
            ),
        }
    )


class _BillableFake(FakeProvider):
    GEN_AI_SYSTEM = "anthropic"


@pytest.mark.asyncio
async def test_run_appends_chat_cost_to_external_sink(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    billable_catalog: Catalog,
) -> None:
    _ = (tracer_provider, reset_active_catalog)
    set_default_catalog(billable_catalog)
    register_provider("anthropic", _BillableFake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    provider: _BillableFake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="hi", tokens_in=10, tokens_out=5, finish_reason="stop"),
    ]

    sink: list[float | None] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    instance = Demo()
    text = await runtime.run(instance, "hello", cost_sink=sink)

    assert text == "hi"
    assert len(sink) == 1
    assert sink[0] is not None
    assert sink[0] > 0


@pytest.mark.asyncio
async def test_run_default_cost_sink_is_optional() -> None:
    """Omitting the kwarg keeps the public contract unchanged."""
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    text = await Demo().run("hello")  # type: ignore[attr-defined]
    assert isinstance(text, str)
    assert text


@pytest.mark.asyncio
async def test_stream_appends_chat_cost_to_external_sink(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    billable_catalog: Catalog,
) -> None:
    _ = (tracer_provider, reset_active_catalog)
    set_default_catalog(billable_catalog)

    class _StreamFake(_BillableFake):
        def __init__(self) -> None:
            super().__init__()
            self.stream_events = [
                Chunk(delta="hi "),
                Chunk(delta="there"),
                Chunk(
                    delta="",
                    finish_reason="stop",
                    usage=ChunkUsage(input_tokens=10, output_tokens=5),
                ),
            ]

    register_provider("anthropic", _StreamFake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    sink: list[float | None] = []
    instance = Demo()
    collected: list[str] = []
    async for chunk in runtime.stream(instance, "hi", cost_sink=sink):
        collected.append(chunk)
    assert "".join(collected) == "hi there"
    assert len(sink) == 1
    assert sink[0] is not None
    assert sink[0] > 0
