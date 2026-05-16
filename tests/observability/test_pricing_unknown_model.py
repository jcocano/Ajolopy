"""Unknown-model warning behaviour for the pricing layer."""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.observability import Catalog
from ajolopy.observability.pricing import set_default_catalog
from ajolopy.providers import register_provider
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


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_get_logs_once_per_unknown_model(caplog: pytest.LogCaptureFixture) -> None:
    catalog = Catalog({})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        assert catalog.get("acme-model-1") is None
        assert catalog.get("acme-model-1") is None  # second call — must NOT re-warn
        assert catalog.get("acme-model-1") is None  # third call — still silent
        assert catalog.get("acme-model-2") is None  # different model — new warning

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    assert len(warnings) == 2
    # Each warning mentions the offending model name + the override path.
    messages = [record.getMessage() for record in warnings]
    assert any("acme-model-1" in msg for msg in messages)
    assert any("acme-model-2" in msg for msg in messages)
    assert all("pricing_overrides" in msg for msg in messages)


@pytest.mark.asyncio
async def test_unknown_model_does_not_break_span_emission(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    """A chat span with an unknown model emits no cost attrs but stays
    otherwise normal — usage tokens, gen_ai.system, finish reasons are
    all there."""
    _ = reset_active_catalog
    set_default_catalog(Catalog({}))
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    text = await Demo().run("hi")  # type: ignore[attr-defined]
    assert text  # FakeProvider's default reply

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    # Cost attrs absent.
    assert "gen_ai.cost_usd" not in attrs
    # Standard AJ-28 attrs still present.
    assert attrs["gen_ai.request.model"] == "claude-opus-4-7"
    assert attrs["gen_ai.usage.input_tokens"] == 1
    assert attrs["gen_ai.usage.output_tokens"] == 2
