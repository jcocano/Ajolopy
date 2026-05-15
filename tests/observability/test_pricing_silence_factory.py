"""Factory plumbing tests for ``AjolopyFactory.create(pricing_silence=...)``.

Mirrors ``test_pricing_overrides.py`` but for the AJ-70 silence kwarg.
Verifies that:

- ``pricing_silence`` flows from the factory kwarg into the active catalog
  so subsequent chat-span emissions are silent for the listed prefixes.
- ``pricing_silence`` composes with ``pricing_overrides`` — both kwargs can
  be passed together and they apply independently.
- Passing ``pricing_silence`` alone (without overrides) still installs a
  fresh active catalog so the silence applies to every future emission.
"""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.di import Container, Injectable
from ajolopy.modules import Module
from ajolopy.observability import Catalog, ModelPrice
from ajolopy.observability.pricing import get_active_catalog, set_default_catalog
from ajolopy.providers import register_provider, register_route
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


@pytest.mark.asyncio
async def test_factory_pricing_silence_installs_catalog_with_silence_list(
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog

    @Injectable
    class _Service:
        pass

    @Module(providers=[_Service])
    class RootModule:
        pass

    from ajolopy.factory import AjolopyFactory

    await AjolopyFactory.create(
        RootModule,
        container=Container(),
        pricing_silence={"vllm", "my-custom-model"},
    )

    catalog = get_active_catalog()
    # Internal observation: the active catalog has the silence list copied
    # in. The frozenset comparison locks the policy in place.
    assert "vllm" in catalog._silence_models
    assert "my-custom-model" in catalog._silence_models


@pytest.mark.asyncio
async def test_factory_pricing_silence_combined_with_overrides(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    """Both kwargs can be passed together; they apply independently."""
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
    await AjolopyFactory.create(
        RootModule,
        container=Container(),
        pricing_overrides=overrides,
        pricing_silence={"vllm"},
    )

    # The override applies (catalog math), the silence applies (warning
    # gate for an unrelated prefix).
    catalog = get_active_catalog()
    price = catalog.get("claude-sonnet-4-7")
    assert price is not None
    assert price.input_cost_per_token == 1e-6
    assert "vllm" in catalog._silence_models


@pytest.mark.asyncio
async def test_factory_pricing_silence_chat_span_stays_quiet(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end: a chat span on a silenced prefix emits zero warnings."""
    _ = reset_active_catalog
    # Custom prefixes route through the universal-openai provider; we
    # register a fake so the runtime can stub the chat call. The autouse
    # ``isolate_registry`` fixture restores the route table after the test.
    register_provider("universal-openai", FakeProvider, overwrite=True)
    register_route("vllm:*", "universal-openai")

    @Injectable
    class _Service:
        pass

    @Module(providers=[_Service])
    class RootModule:
        pass

    from ajolopy.factory import AjolopyFactory

    await AjolopyFactory.create(
        RootModule,
        container=Container(),
        pricing_silence={"vllm"},
    )

    @Agent(model="vllm:my-onprem-model", system="…")
    class Demo:
        pass

    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        await Demo().run("hi")  # type: ignore[attr-defined]
    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    assert warnings == []

    # Chat span still has no cost attrs (the silence does not invent prices).
    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    assert "gen_ai.cost_usd" not in _attrs(chat)


@pytest.mark.asyncio
async def test_factory_no_kwargs_falls_back_to_lazy_default(
    reset_active_catalog: None,
) -> None:
    """No kwargs → ``set_default_catalog(None)`` so future calls fall back
    to :meth:`Catalog.load_default` lazily — the AJ-30 default behaviour."""
    _ = reset_active_catalog

    @Injectable
    class _Service:
        pass

    @Module(providers=[_Service])
    class RootModule:
        pass

    from ajolopy.factory import AjolopyFactory

    # Pre-poison: install a catalog so we can prove ``create()`` clears it.
    set_default_catalog(Catalog({}, silence_models={"sentinel"}))

    await AjolopyFactory.create(RootModule, container=Container())

    catalog = get_active_catalog()
    # The active catalog falls back to the snapshot default, which has no
    # silence list — the previous policy is gone.
    assert "sentinel" not in catalog._silence_models
    # And it actually carries the LiteLLM snapshot data.
    assert len(catalog) > 1000
