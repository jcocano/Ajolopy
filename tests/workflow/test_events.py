"""Stream event schema and ordering invariants for ``@Workflow``.

Covers the "Stream event schema" acceptance group: ``stream()`` yields
plain dicts (no bare strings, no Pydantic models); the default and
override paths have well-defined event orderings; the terminal
``done`` event's text equals ``run()``'s awaited result with the same
mocked provider input; ``run()`` is implemented in terms of
``stream()`` so both paths produce identical provider call sequences.
"""

from typing import Any

import pytest

from ajolopy import Agent, Workflow
from ajolopy.providers import Chunk, Response, ToolCallDelta, register_provider

from .conftest import ScriptedStreamProvider


def _register() -> None:
    register_provider("anthropic", ScriptedStreamProvider, overwrite=True)


def _delegate_round(tool_name: str, message: str) -> list[Chunk]:
    return [
        Chunk(
            delta="",
            tool_call_delta=ToolCallDelta(id="c1", name=tool_name, index=0),
        ),
        Chunk(
            delta="",
            tool_call_delta=ToolCallDelta(
                id="",
                arguments_delta=f'{{"message":"{message}"}}',
                index=0,
            ),
        ),
        Chunk(delta="", finish_reason="tool_calls"),
    ]


def _final_round(text: str) -> list[Chunk]:
    return [Chunk(delta=text), Chunk(delta="", finish_reason="stop")]


@pytest.mark.asyncio
async def test_stream_yields_dict_objects_only() -> None:
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-sonnet-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [_final_round("ok")]

    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        assert isinstance(event, dict)
        assert "type" in event


@pytest.mark.asyncio
async def test_default_path_orders_events_handoff_agent_result_token_done() -> None:
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-sonnet-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [
        _delegate_round("delegate_to_billing", "refund"),
        _final_round("done"),
    ]

    events: list[dict[str, Any]] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    types_only = [e["type"] for e in events]
    # First two events: handoff -> agent_result per delegation.
    assert types_only[:2] == ["handoff", "agent_result"]
    # Final event is done.
    assert types_only[-1] == "done"
    # Token events (if any) are emitted before the final done.
    assert all(t in {"handoff", "agent_result", "token", "done"} for t in types_only)


@pytest.mark.asyncio
async def test_override_path_event_sequence_is_handoff_agent_result_done() -> None:
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    billing_provider: ScriptedStreamProvider = Billing._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    billing_provider.responses = [Response(text="answer", finish_reason="stop")]

    @Workflow(agents=[Billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return Billing

    events: list[dict[str, Any]] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    types_only = [e["type"] for e in events]
    assert types_only == ["handoff", "agent_result", "done"]


@pytest.mark.asyncio
async def test_done_text_matches_run_result() -> None:
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-sonnet-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [_final_round("the answer")]
    streamed_done_text = ""
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        if event["type"] == "done":
            streamed_done_text = event["text"]

    # Reset the provider's round counter so ``run()`` sees the same script.
    coordinator._round_index = 0
    coordinator.stream_calls.clear()
    coordinator.stream_rounds = [_final_round("the answer")]
    run_text: str = await Team().run("hi")  # type: ignore[attr-defined]
    assert streamed_done_text == run_text
    assert run_text == "the answer"


@pytest.mark.asyncio
async def test_run_consumes_stream_internally() -> None:
    """Confirm run() drives the same provider calls as stream() does."""
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-sonnet-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [_final_round("yes")]
    # run() drains its own stream(); no separate complete() call should fire.
    assert await Team().run("x") == "yes"  # type: ignore[attr-defined]
    assert coordinator.complete_calls == []  # No complete() call observed.
    assert len(coordinator.stream_calls) == 1


@pytest.mark.asyncio
async def test_token_events_only_emitted_on_final_turn() -> None:
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-sonnet-4-7", agents=[Billing])
    class Team:
        pass

    coordinator: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    # Tool-calling turn that ALSO emits text deltas. The text deltas
    # must NOT appear as token events because the turn carries a tool_call.
    coordinator.stream_rounds = [
        [
            Chunk(delta="thinking..."),
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
        ],
        _final_round("done"),
    ]

    events: list[dict[str, Any]] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    tokens = [e for e in events if e["type"] == "token"]
    # The only tokens that may appear belong to the final tool-free turn.
    # The tool-calling turn's "thinking..." delta MUST be suppressed.
    assert all(t["text"] != "thinking..." for t in tokens)
