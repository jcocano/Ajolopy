"""Tests for the ``pricing_overrides=`` escape hatch on the factory."""

from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.di import Container, Injectable
from ajolopy.modules import Module
from ajolopy.observability import Catalog, ModelPrice, compute_cost_usd
from ajolopy.observability.pricing import (
    get_active_catalog,
    set_default_catalog,
)
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


def test_with_overrides_adds_new_acme_model_for_compute_cost_usd() -> None:
    catalog = Catalog({}).with_overrides(
        {"acme-model": ModelPrice(input_cost_per_token=1e-6, output_cost_per_token=3e-6)}
    )
    cost = compute_cost_usd("acme-model", input_tokens=1000, catalog=catalog)
    assert cost == pytest.approx(0.001)


@pytest.mark.asyncio
async def test_factory_pricing_overrides_flow_through_to_chat_span(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Injectable
    class _Service:
        pass

    @Module(providers=[_Service])
    class RootModule:
        pass

    from ajolopy.factory import AjolopyFactory

    overrides = {
        "claude-sonnet-4-7": ModelPrice(input_cost_per_token=1e-6, output_cost_per_token=2e-6)
    }
    # Build a small app just to exercise the factory's plumbing — the
    # module graph itself is irrelevant for the catalog assertion.
    await AjolopyFactory.create(
        RootModule,
        container=Container(),
        pricing_overrides=overrides,
    )

    # Active catalog must now resolve the override.
    catalog = get_active_catalog()
    price = catalog.get("claude-sonnet-4-7")
    assert price is not None
    assert price.input_cost_per_token == 1e-6

    # Decorating an agent AFTER the factory bootstrap also picks up the
    # override on first chat-span emission (lazy catalog resolution).
    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]
    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    # FakeProvider's default reply: tokens_in=1, tokens_out=2.
    expected = 1 * 1e-6 + 2 * 2e-6
    assert attrs["gen_ai.cost_usd"] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_decoration_before_factory_picks_up_overrides_lazily(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    """The runtime resolves the catalog at FIRST run, so an agent decorated
    before the factory bootstrap still bills against the override."""
    _ = reset_active_catalog
    register_provider("anthropic", FakeProvider, overwrite=True)

    # 1) Decorate first — no catalog wired yet.
    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    # 2) Bootstrap with overrides — installs the active catalog.
    from ajolopy.factory import AjolopyFactory

    @Injectable
    class _Service:
        pass

    @Module(providers=[_Service])
    class RootModule:
        pass

    overrides = {
        "claude-sonnet-4-7": ModelPrice(input_cost_per_token=4e-6, output_cost_per_token=8e-6)
    }
    await AjolopyFactory.create(RootModule, container=Container(), pricing_overrides=overrides)

    # 3) Run — the runtime resolves the active catalog lazily.
    await Demo().run("hi")  # type: ignore[attr-defined]
    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    expected = 1 * 4e-6 + 2 * 8e-6
    assert _attrs(chat)["gen_ai.cost_usd"] == pytest.approx(expected)
