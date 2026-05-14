"""Tests for the ``ajolopy.cost_usd.total`` root-span roll-up."""

from collections.abc import Iterator
from typing import Any, override

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy import Tool as ToolDecorator
from ajolopy.observability import Catalog, ModelPrice
from ajolopy.observability.pricing import set_default_catalog
from ajolopy.providers import (
    LLMProviderError,
    Response,
    ToolCall,
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


@pytest.fixture
def reset_active_catalog() -> Iterator[None]:
    try:
        yield
    finally:
        set_default_catalog(None)


@pytest.fixture
def sonnet_catalog() -> Catalog:
    return Catalog(
        {
            "claude-sonnet-4-7": ModelPrice(
                input_cost_per_token=3e-6,
                output_cost_per_token=15e-6,
            ),
            "claude-fallback-1": ModelPrice(
                input_cost_per_token=1e-6,
                output_cost_per_token=2e-6,
            ),
        }
    )


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


class _BillableFake(FakeProvider):
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
        # Honour the queued responses if any (so tests can prime a tool
        # loop), otherwise return a billable default for the model.
        await super().complete(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
        )
        return Response(text="ok", tokens_in=100, tokens_out=50, finish_reason="stop")


@pytest.mark.asyncio
async def test_single_chat_call_roll_up(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    sonnet_catalog: Catalog,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(sonnet_catalog)
    register_provider("anthropic", _BillableFake, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    invoke = _find(spans, "agent.invoke ")[0]
    chat = _find(spans, "chat ")[0]
    chat_cost = _attrs(chat)["gen_ai.cost_usd"]
    assert _attrs(invoke)["ajolopy.cost_usd.total"] == pytest.approx(chat_cost)


class _ToolLoopFake(FakeProvider):
    """First call asks for a tool; second call wraps up. Both billable."""

    GEN_AI_SYSTEM = "anthropic"


@pytest.mark.asyncio
async def test_tool_loop_sums_children_into_root(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    sonnet_catalog: Catalog,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(sonnet_catalog)
    register_provider("anthropic", _ToolLoopFake, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class DemoAgent:
        @ToolDecorator
        def ping(self) -> str:
            """Trivial tool used by the loop."""
            return "pong"

    provider = DemoAgent._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    assert isinstance(provider, FakeProvider)
    provider.responses = [
        Response(
            text="",
            tool_calls=[ToolCall(id="t1", name="ping", arguments={})],
            tokens_in=100,
            tokens_out=10,
            finish_reason="tool_calls",
        ),
        Response(text="done", tokens_in=50, tokens_out=20, finish_reason="stop"),
    ]

    await DemoAgent().run("invoke me")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    invoke = _find(spans, "agent.invoke ")[0]
    chats = _find(spans, "chat ")
    assert len(chats) == 2
    expected = sum(_attrs(c)["gen_ai.cost_usd"] for c in chats)
    assert _attrs(invoke)["ajolopy.cost_usd.total"] == pytest.approx(expected)


class _PartialKnownFake(FakeProvider):
    """Fallback path: failing primary then a successful billable secondary."""

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
        if "fail" in model:
            raise LLMProviderError("simulated outage")
        return Response(text="ok", tokens_in=100, tokens_out=50)


@pytest.mark.asyncio
async def test_root_total_handles_failed_unknown_child(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    sonnet_catalog: Catalog,
) -> None:
    """A failing chat span has no cost — the root rolls up just the
    successful child's cost (the spec's "at least one known child" rule)."""
    _ = reset_active_catalog
    set_default_catalog(sonnet_catalog)
    register_provider("anthropic", _PartialKnownFake, overwrite=True)

    @Agent(model="claude-fail", system="…", fallback="claude-sonnet-4-7")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    invoke = _find(spans, "agent.invoke ")[0]
    success_chat = next(
        c
        for c in _find(spans, "chat ")
        if _attrs(c).get("gen_ai.request.model") == "claude-sonnet-4-7"
    )
    assert _attrs(invoke)["ajolopy.cost_usd.total"] == pytest.approx(
        _attrs(success_chat)["gen_ai.cost_usd"]
    )


@pytest.mark.asyncio
async def test_root_total_omitted_when_every_child_unknown(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(Catalog({}))  # empty — every model is unknown
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hi")  # type: ignore[attr-defined]
    invoke = _find(list(tracer_provider.get_finished_spans()), "agent.invoke ")[0]
    assert "ajolopy.cost_usd.total" not in _attrs(invoke)
