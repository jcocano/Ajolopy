"""Tests for the private ``tool_calls_sink`` kwarg on ``AgentRuntime.run``.

Mirrors :mod:`tests.agent.test_runtime_cost_sink`. The kwarg is the
orchestrator hook AJ-26's ``EvalRunner`` uses to stamp
:attr:`~ajolopy.eval.results.EvalOutput.tool_calls`. Only SUCCESSFUL
dispatches append — validation errors and tool exceptions do NOT.
"""

import pytest

from ajolopy import Agent, Tool
from ajolopy.providers import Response, ToolCall, register_provider
from tests.agent.conftest import FakeProvider


@pytest.mark.asyncio
async def test_run_appends_successful_tool_name() -> None:
    """A successful tool dispatch lands its name in the sink."""

    class _Fake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

    register_provider("anthropic", _Fake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool(description="Look up an order by id")
        def lookup_order(self, order_id: str) -> str:
            return f"order {order_id}: shipped"

    provider: _Fake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(
            text="",
            tool_calls=[
                ToolCall(id="call_1", name="lookup_order", arguments={"order_id": "42"}),
            ],
            tokens_in=1,
            tokens_out=1,
            finish_reason="tool_calls",
        ),
        Response(text="all done", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    sink: list[str] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    text = await runtime.run(Demo(), "find order 42", tool_calls_sink=sink)
    assert text == "all done"
    assert sink == ["lookup_order"]


@pytest.mark.asyncio
async def test_run_default_sink_is_optional() -> None:
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    text = await Demo().run("hello")  # type: ignore[attr-defined]
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_validation_failure_does_not_append() -> None:
    """A validation error on the tool call must NOT land in the sink."""

    class _Fake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

    register_provider("anthropic", _Fake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool(description="Need an int arg")
        def needs_int(self, value: int) -> str:
            return str(value)

    provider: _Fake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(
            text="",
            tool_calls=[
                # ``value`` is not coercible to int — Pydantic validation
                # rejects it BEFORE the tool runs.
                ToolCall(id="c1", name="needs_int", arguments={"value": "not-a-number"}),
            ],
            tokens_in=1,
            tokens_out=1,
            finish_reason="tool_calls",
        ),
        Response(text="recovered", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    sink: list[str] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    text = await runtime.run(Demo(), "broken", tool_calls_sink=sink)
    assert text == "recovered"
    assert sink == []


@pytest.mark.asyncio
async def test_tool_exception_does_not_append() -> None:
    """A tool method that raises must NOT land in the sink."""

    class _Fake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

    register_provider("anthropic", _Fake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool(description="Always raises")
        def broken(self) -> str:
            raise RuntimeError("tool boom")

    provider: _Fake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(
            text="",
            tool_calls=[ToolCall(id="c1", name="broken", arguments={})],
            tokens_in=1,
            tokens_out=1,
            finish_reason="tool_calls",
        ),
        Response(text="recovered", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    sink: list[str] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    text = await runtime.run(Demo(), "broken", tool_calls_sink=sink)
    assert text == "recovered"
    assert sink == []


@pytest.mark.asyncio
async def test_multiple_tools_dispatch_order_preserved() -> None:
    """When the LLM requests multiple tools in one round, names land in call order."""

    class _Fake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

    register_provider("anthropic", _Fake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool(description="Tool A")
        def tool_a(self) -> str:
            return "A"

        @Tool(description="Tool B")
        def tool_b(self) -> str:
            return "B"

    provider: _Fake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(
            text="",
            tool_calls=[
                ToolCall(id="c1", name="tool_a", arguments={}),
                ToolCall(id="c2", name="tool_b", arguments={}),
            ],
            tokens_in=1,
            tokens_out=1,
            finish_reason="tool_calls",
        ),
        Response(text="done", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    sink: list[str] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    await runtime.run(Demo(), "go", tool_calls_sink=sink)
    assert sink == ["tool_a", "tool_b"]


@pytest.mark.asyncio
async def test_async_tool_also_appends() -> None:
    """Async tool dispatch lands in the sink the same way sync ones do."""

    class _Fake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

    register_provider("anthropic", _Fake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool(description="Async tool")
        async def fetch(self, key: str) -> str:
            return f"value for {key}"

    provider: _Fake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(
            text="",
            tool_calls=[ToolCall(id="c1", name="fetch", arguments={"key": "x"})],
            tokens_in=1,
            tokens_out=1,
            finish_reason="tool_calls",
        ),
        Response(text="ok", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    sink: list[str] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    await runtime.run(Demo(), "go", tool_calls_sink=sink)
    assert sink == ["fetch"]


@pytest.mark.asyncio
async def test_unknown_tool_name_does_not_append() -> None:
    """The model requesting an unknown tool must NOT count as 'used'."""

    class _Fake(FakeProvider):
        GEN_AI_SYSTEM = "anthropic"

    register_provider("anthropic", _Fake, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool(description="Existing tool")
        def real_tool(self) -> str:
            return "ok"

    provider: _Fake = Demo._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(
            text="",
            tool_calls=[ToolCall(id="c1", name="nonexistent", arguments={})],
            tokens_in=1,
            tokens_out=1,
            finish_reason="tool_calls",
        ),
        Response(text="ok", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    sink: list[str] = []
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    await runtime.run(Demo(), "go", tool_calls_sink=sink)
    assert sink == []
