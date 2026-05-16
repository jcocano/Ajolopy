"""Coordinator tool-calling loop tests for ``@Workflow``.

Covers the "Coordinator tool-calling loop (default path)" acceptance
group: the default magical path drives a synthetic coordinator with one
``delegate_to_<agent>`` tool per registered agent, dispatches each
tool_call against the matching agent's ``run()``, and stops when the
coordinator emits a tool-free response.
"""

from collections.abc import AsyncIterator
from typing import override

import pytest

from ajolopy import Agent, Workflow
from ajolopy.agent import AgentError
from ajolopy.providers import Chunk, Message, Response, Tool, ToolCallDelta, register_provider
from ajolopy.workflow import WorkflowMaxStepsError

from .conftest import ScriptedStreamProvider

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _delegate_call_round(
    *,
    call_id: str,
    tool_name: str,
    forwarded_message: str,
) -> list[Chunk]:
    """Build a Chunk stream simulating one provider tool_call response."""
    return [
        Chunk(
            delta="",
            tool_call_delta=ToolCallDelta(id=call_id, name=tool_name, index=0),
        ),
        Chunk(
            delta="",
            tool_call_delta=ToolCallDelta(
                id="",
                arguments_delta=f'{{"message":"{forwarded_message}"}}',
                index=0,
            ),
        ),
        Chunk(delta="", finish_reason="tool_calls"),
    ]


def _tool_free_round(text: str) -> list[Chunk]:
    """Build a Chunk stream simulating one tool-free coordinator response."""
    return [
        Chunk(delta=text),
        Chunk(delta="", finish_reason="stop"),
    ]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_delegation_returns_coordinator_final_text(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing specialist."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    # The coordinator delegates once to Billing, then writes a final answer.
    coordinator_provider: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator_provider.stream_rounds = [
        _delegate_call_round(
            call_id="c1",
            tool_name="delegate_to_billing",
            forwarded_message="refund",
        ),
        _tool_free_round("Your refund is on the way."),
    ]
    # The delegated Billing agent's underlying provider responds via complete().
    billing_provider: ScriptedStreamProvider = Billing._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    assert isinstance(billing_provider, ScriptedStreamProvider)

    result = await Team().run("refund please")  # type: ignore[attr-defined]
    assert result == "Your refund is on the way."


@pytest.mark.asyncio
async def test_synthetic_tools_use_lower_classname(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Triage:
        """Classify incoming requests."""

    @Agent(model="claude-opus-4-7", system="…")
    class Technical:
        """Bugs and integration help."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Triage, Technical])
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    coordinator_provider.stream_rounds = [_tool_free_round("done")]

    await Team().run("hello")  # type: ignore[attr-defined]

    # Inspect the tool list sent to the provider on the first stream call.
    first_call = coordinator_provider.stream_calls[0]
    tools: list[Tool] = first_call["tools"]  # type: ignore[assignment]
    assert [t.name for t in tools] == ["delegate_to_triage", "delegate_to_technical"]


@pytest.mark.asyncio
async def test_synthetic_tool_description_uses_docstring(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Refunds, invoices and subscriptions."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    coordinator_provider.stream_rounds = [_tool_free_round("ok")]

    await Team().run("hi")  # type: ignore[attr-defined]
    tools: list[Tool] = coordinator_provider.stream_calls[0]["tools"]  # type: ignore[assignment]
    assert tools[0].description == "Refunds, invoices and subscriptions."


@pytest.mark.asyncio
async def test_synthetic_tool_description_falls_back_for_empty_docstring(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Plain:
        pass

    @Workflow(coordinator="claude-opus-4-7", agents=[Plain])
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    coordinator_provider.stream_rounds = [_tool_free_round("ok")]
    await Team().run("hi")  # type: ignore[attr-defined]
    tools: list[Tool] = coordinator_provider.stream_calls[0]["tools"]  # type: ignore[assignment]
    assert tools[0].description == "Delegate to the Plain agent."


@pytest.mark.asyncio
async def test_coordinator_can_delegate_to_same_agent_twice(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing specialist."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator_provider.stream_rounds = [
        _delegate_call_round(
            call_id="c1", tool_name="delegate_to_billing", forwarded_message="first"
        ),
        _delegate_call_round(
            call_id="c2", tool_name="delegate_to_billing", forwarded_message="second"
        ),
        _tool_free_round("done"),
    ]

    events: list[dict[str, object]] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    handoffs = [e for e in events if e["type"] == "handoff"]
    assert [e["message"] for e in handoffs] == ["first", "second"]


@pytest.mark.asyncio
async def test_parallel_tool_calls_run_sequentially_in_arrival_order(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Agent(model="claude-opus-4-7", system="…")
    class Technical:
        """Technical."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing, Technical])
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    coordinator_provider.stream_rounds = [
        # Both tool_calls in one turn (different indices).
        [
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(id="c1", name="delegate_to_billing", index=0),
            ),
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(
                    id="",
                    arguments_delta='{"message":"billing-msg"}',
                    index=0,
                ),
            ),
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(id="c2", name="delegate_to_technical", index=1),
            ),
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(
                    id="",
                    arguments_delta='{"message":"tech-msg"}',
                    index=1,
                ),
            ),
            Chunk(delta="", finish_reason="tool_calls"),
        ],
        _tool_free_round("answer"),
    ]

    events: list[dict[str, object]] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    typed = [e["type"] for e in events]
    # handoff -> agent_result repeats per call in arrival order, optionally
    # followed by token events for the final coordinator turn and a
    # terminal done event.
    assert typed[:4] == ["handoff", "agent_result", "handoff", "agent_result"]
    assert typed[-1] == "done"
    assert events[0]["agent"] == "Billing"
    assert events[2]["agent"] == "Technical"


@pytest.mark.asyncio
async def test_max_steps_cap_raises_workflow_max_steps_error(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing], max_steps=2)
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    # Always delegate; never let the loop exit.
    coordinator_provider.stream_rounds = [
        _delegate_call_round(call_id="c1", tool_name="delegate_to_billing", forwarded_message="x"),
        _delegate_call_round(call_id="c2", tool_name="delegate_to_billing", forwarded_message="x"),
        _delegate_call_round(call_id="c3", tool_name="delegate_to_billing", forwarded_message="x"),
    ]

    with pytest.raises(WorkflowMaxStepsError) as info:
        await Team().run("hi")  # type: ignore[attr-defined]
    assert info.value.max_steps == 2
    assert info.value.step_count == 2


@pytest.mark.asyncio
async def test_delegated_agent_error_surfaces_as_agent_result_and_recovers(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Flaky:
        """Sometimes fails."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Flaky])
    class Team:
        pass

    # Make Flaky's underlying agent runtime raise an AgentError on the call.
    class _AlwaysFails(ScriptedStreamProvider):
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
            _ = (model, messages, tools, temperature, max_tokens, cache)
            raise AgentError("flaky agent failed")

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
            # Coordinator stream still works; only the agent's complete fails.
            return super().stream(
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                cache=cache,
            )

    # Swap Flaky's provider so its run() raises.
    register_provider("anthropic", _AlwaysFails, overwrite=True)

    # Rebuild Flaky after registering the failing provider so the agent
    # binds to it. We can do that by re-decorating a fresh class.
    @Agent(model="claude-opus-4-7", system="…")
    class FlakyReal:
        """Sometimes fails."""

    @Workflow(coordinator="claude-opus-4-7", agents=[FlakyReal])
    class TeamReal:
        pass

    coordinator_provider: ScriptedStreamProvider = (
        TeamReal._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator_provider.stream_rounds = [
        _delegate_call_round(
            call_id="c1", tool_name="delegate_to_flakyreal", forwarded_message="x"
        ),
        _tool_free_round("recovered"),
    ]

    events: list[dict[str, object]] = []
    async for event in TeamReal().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    typed = [e["type"] for e in events]
    # handoff -> agent_result, optionally token deltas, then done.
    assert typed[:2] == ["handoff", "agent_result"]
    assert typed[-1] == "done"
    # The agent_result event carries the error text.
    error_output = str(events[1]["output"])
    assert "AgentError" in error_output or "flaky" in error_output
    assert events[-1]["text"] == "recovered"


@pytest.mark.asyncio
async def test_coordinator_llm_provider_error_propagates_out(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    from ajolopy.providers import LLMProviderError

    coordinator_provider: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator_provider.raise_on_stream = LLMProviderError("coordinator boom")

    with pytest.raises(LLMProviderError, match="coordinator boom"):
        async for _ in Team().stream("hi"):  # type: ignore[attr-defined]
            pass


@pytest.mark.asyncio
async def test_unknown_tool_name_pushes_error_result_back_to_coordinator(
    scripted_stream_provider: type[ScriptedStreamProvider],
) -> None:
    _ = scripted_stream_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-opus-4-7", agents=[Billing])
    class Team:
        pass

    coordinator_provider: ScriptedStreamProvider = Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    coordinator_provider.stream_rounds = [
        _delegate_call_round(call_id="c1", tool_name="delegate_to_unknown", forwarded_message="x"),
        _tool_free_round("oops"),
    ]

    events: list[dict[str, object]] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        events.append(dict(event))

    # No handoff event fires for an unknown tool name; the workflow still
    # recovers because the coordinator gets an error tool_result.
    typed = [e["type"] for e in events]
    assert "handoff" not in typed
    assert typed[-1] == "done"
    assert events[-1]["text"] == "oops"
