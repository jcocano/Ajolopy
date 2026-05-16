"""Observability spans + cost roll-up tests for ``@Workflow``.

Covers the "Observability" acceptance group: the span tree shape, the
``ajolopy.workflow.*`` attribute set on the root, the
``ajolopy.workflow.handoff.from`` / ``handoff.to`` breadcrumbs on each
delegation, and the cost roll-up that aggregates every descendant
``chat`` span's ``gen_ai.cost_usd`` into the workflow's
``ajolopy.cost_usd.total``.
"""

from collections.abc import Iterator
from typing import Any, override

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent, Workflow
from ajolopy.observability import Catalog, ModelPrice
from ajolopy.observability.pricing import set_default_catalog
from ajolopy.providers import (
    Chunk,
    ChunkUsage,
    Message,
    Response,
    Tool,
    ToolCallDelta,
    register_provider,
)
from tests.observability.conftest import ensure_session_provider

from .conftest import ScriptedStreamProvider


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


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


class _BillableStreamProvider(ScriptedStreamProvider):
    GEN_AI_SYSTEM = "anthropic"

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
        await super().complete(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
        )
        return Response(text="ok", tokens_in=100, tokens_out=50, finish_reason="stop")


def _terminal_usage_chunk(input_tokens: int, output_tokens: int) -> Chunk:
    return Chunk(
        delta="",
        finish_reason="stop",
        usage=ChunkUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.mark.asyncio
async def test_workflow_run_emits_root_span_with_full_attribute_set(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    register_provider("anthropic", _BillableStreamProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing], max_steps=3)
    class Team:
        pass

    coordinator: _BillableStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [
        [Chunk(delta="ok"), _terminal_usage_chunk(10, 5)],
    ]

    await Team().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    invoke = _find(spans, "workflow.invoke ")[0]
    assert invoke.name == "workflow.invoke Team"
    a = _attrs(invoke)
    assert a["ajolopy.workflow.name"] == "Team"
    assert a["ajolopy.workflow.operation"] == "run"
    assert a["ajolopy.workflow.coordinator.model"] == "claude-opus-4-7"
    assert a["ajolopy.workflow.max_steps"] == 3
    assert a["ajolopy.workflow.step_count"] == 1
    assert a["ajolopy.workflow.handoff.count"] == 0


@pytest.mark.asyncio
async def test_default_path_span_tree(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    register_provider("anthropic", _BillableStreamProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: _BillableStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [
        # turn 1: delegate
        [
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(id="c1", name="delegate_to_billing", index=0),
            ),
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(
                    id="",
                    arguments_delta='{"message":"x"}',
                    index=0,
                ),
            ),
            Chunk(delta="", finish_reason="tool_calls"),
            _terminal_usage_chunk(20, 10),
        ],
        # turn 2: final
        [Chunk(delta="done"), _terminal_usage_chunk(10, 5)],
    ]

    await Team().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    workflow_spans = _find(spans, "workflow.invoke ")
    chats = _find(spans, "chat ")
    agent_invokes = _find(spans, "agent.invoke ")
    assert len(workflow_spans) == 1
    # 2 coordinator turns + 1 chat from delegated Billing agent run = 3.
    assert len(chats) == 3
    # 1 wrapper agent.invoke from workflow + 1 nested from the agent runtime.
    assert len(agent_invokes) == 2


@pytest.mark.asyncio
async def test_route_path_emits_no_coordinator_chat_span(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    register_provider("anthropic", _BillableStreamProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(agents=[Billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return Billing

    await Team().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    workflow_spans = _find(spans, "workflow.invoke ")
    chats = _find(spans, "chat ")
    agent_invokes = _find(spans, "agent.invoke ")
    assert len(workflow_spans) == 1
    # Only one chat span — the delegated Billing agent's own LLM call.
    assert len(chats) == 1
    # 1 wrapper + 1 nested agent.invoke span.
    assert len(agent_invokes) == 2
    # coordinator.model attribute is absent on the override path.
    assert "ajolopy.workflow.coordinator.model" not in _attrs(workflow_spans[0])
    assert "ajolopy.workflow.max_steps" not in _attrs(workflow_spans[0])


@pytest.mark.asyncio
async def test_cost_roll_up_sums_all_descendant_chat_costs(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    billable_catalog: Catalog,
) -> None:
    _ = reset_active_catalog
    set_default_catalog(billable_catalog)
    register_provider("anthropic", _BillableStreamProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: _BillableStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [
        # turn 1: final
        [Chunk(delta="done"), _terminal_usage_chunk(100, 50)],
    ]

    await Team().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    workflow = _find(spans, "workflow.invoke ")[0]
    chats = _find(spans, "chat ")
    chat_costs = [_attrs(c)["gen_ai.cost_usd"] for c in chats if "gen_ai.cost_usd" in _attrs(c)]
    assert chat_costs
    assert _attrs(workflow)["ajolopy.cost_usd.total"] == pytest.approx(sum(chat_costs))


@pytest.mark.asyncio
async def test_handoff_breadcrumbs_on_default_path(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    register_provider("anthropic", _BillableStreamProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: _BillableStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [
        [
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(id="c1", name="delegate_to_billing", index=0),
            ),
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(
                    id="",
                    arguments_delta='{"message":"x"}',
                    index=0,
                ),
            ),
            Chunk(delta="", finish_reason="tool_calls"),
            _terminal_usage_chunk(10, 5),
        ],
        [Chunk(delta="done"), _terminal_usage_chunk(10, 5)],
    ]

    await Team().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    # The workflow's wrapper agent.invoke span carries the breadcrumb.
    wrappers = [
        s for s in _find(spans, "agent.invoke ") if "ajolopy.workflow.handoff.from" in _attrs(s)
    ]
    assert wrappers
    attrs = _attrs(wrappers[0])
    assert attrs["ajolopy.workflow.handoff.from"] == "coordinator"
    assert attrs["ajolopy.workflow.handoff.to"] == "Billing"


@pytest.mark.asyncio
async def test_handoff_breadcrumbs_on_route_path(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
) -> None:
    _ = reset_active_catalog
    register_provider("anthropic", _BillableStreamProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(agents=[Billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return Billing

    await Team().run("hi")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    wrappers = [
        s for s in _find(spans, "agent.invoke ") if "ajolopy.workflow.handoff.from" in _attrs(s)
    ]
    assert wrappers
    attrs = _attrs(wrappers[0])
    assert attrs["ajolopy.workflow.handoff.from"] == "route"
    assert attrs["ajolopy.workflow.handoff.to"] == "Billing"
