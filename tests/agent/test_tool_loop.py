"""Tests for the function-calling loop inside ``AgentRuntime``.

Covers the "Function-calling loop on ``run()``", "Function-calling loop on
``stream()``" and "Observability" acceptance groups of ``specs/tool.md``.
"""

import json
from typing import override
from unittest.mock import patch

import pytest

from ajolopy import Agent, Tool
from ajolopy.agent import AgentToolLoopError
from ajolopy.providers import (
    Chunk,
    Message,
    Response,
    ToolCall,
    ToolCallDelta,
    register_provider,
)

from .conftest import FakeProvider

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _ScriptedProvider(FakeProvider):
    """Provider that returns scripted Responses (and Chunks) round by round."""


def _register(provider_cls: type[_ScriptedProvider]) -> None:
    register_provider("anthropic", provider_cls, overwrite=True)


# ---------------------------------------------------------------------------
# run() — non-streaming loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_tool_call_executes_and_response_returns_text() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[ToolCall(id="t1", name="echo", arguments={"value": "ping"})],
                    finish_reason="tool_calls",
                ),
                Response(text="final answer", finish_reason="stop"),
            ]

    _register(Prov)

    invocations: list[str] = []

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            invocations.append(value)
            return value

    assert await Demo().run("hi") == "final answer"  # type: ignore[attr-defined]
    assert invocations == ["ping"]


@pytest.mark.asyncio
async def test_second_complete_receives_tool_result_message() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[ToolCall(id="abc", name="echo", arguments={"value": "x"})],
                    finish_reason="tool_calls",
                ),
                Response(text="done", finish_reason="stop"),
            ]

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            return f"echoed:{value}"

    instance = Demo()
    await instance.run("hi")  # type: ignore[attr-defined]

    provider: Prov = instance._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    assert len(provider.complete_calls) == 2
    second_messages: list[Message] = provider.complete_calls[1]["messages"]  # type: ignore[assignment]
    roles = [m.role for m in second_messages]
    assert roles[-2:] == ["assistant", "tool"]
    tool_msg = second_messages[-1]
    assert tool_msg.tool_call_id == "abc"
    assert "echoed:x" in tool_msg.content
    assistant_msg = second_messages[-2]
    assert assistant_msg.tool_calls
    assert assistant_msg.tool_calls[0].name == "echo"


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_response_all_dispatch() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[
                        ToolCall(id="a", name="echo", arguments={"value": "1"}),
                        ToolCall(id="b", name="echo", arguments={"value": "2"}),
                    ],
                    finish_reason="tool_calls",
                ),
                Response(text="combined", finish_reason="stop"),
            ]

    _register(Prov)

    seen: list[str] = []

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            seen.append(value)
            return value

    assert await Demo().run("hi") == "combined"  # type: ignore[attr-defined]
    assert sorted(seen) == ["1", "2"]


@pytest.mark.asyncio
async def test_sync_tool_dispatched_via_to_thread() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[ToolCall(id="s1", name="upper", arguments={"value": "hi"})],
                    finish_reason="tool_calls",
                ),
                Response(text="done", finish_reason="stop"),
            ]

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        def upper(self, value: str) -> str:
            """Upper."""
            return value.upper()

    to_thread_path = "ajolopy.agent.runtime.asyncio.to_thread"
    with patch(to_thread_path, wraps=__import__("asyncio").to_thread) as m:
        await Demo().run("hi")  # type: ignore[attr-defined]
    assert m.called


@pytest.mark.asyncio
async def test_tool_raises_surfaces_as_error_tool_result_and_loop_continues() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[ToolCall(id="r1", name="boom", arguments={})],
                    finish_reason="tool_calls",
                ),
                Response(text="recovered", finish_reason="stop"),
            ]

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def boom(self) -> str:
            """Always raises."""
            msg = "kaboom"
            raise ValueError(msg)

    instance = Demo()
    assert await instance.run("hi") == "recovered"  # type: ignore[attr-defined]
    provider: Prov = instance._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    tool_msg = provider.complete_calls[1]["messages"][-1]  # type: ignore[index]
    assert tool_msg.is_error is True
    assert "ValueError" in tool_msg.content


@pytest.mark.asyncio
async def test_max_tool_iterations_caps_the_loop() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            # Always demand another tool call. The runtime should give up
            # after `max_tool_iterations` attempts.
            self._round = 0

        @override
        async def complete(self, **kwargs: object) -> Response:
            self.complete_calls.append(kwargs)
            self._round += 1
            return Response(
                text="",
                tool_calls=[ToolCall(id=f"t{self._round}", name="echo", arguments={"value": "x"})],
                finish_reason="tool_calls",
            )

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…", max_tool_iterations=2)
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            return value

    with pytest.raises(AgentToolLoopError, match="max_tool_iterations=2"):
        await Demo().run("hi")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_unknown_tool_call_returns_error_result_to_model() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[ToolCall(id="u1", name="ghost", arguments={})],
                    finish_reason="tool_calls",
                ),
                Response(text="oops", finish_reason="stop"),
            ]

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            return value

    instance = Demo()
    assert await instance.run("hi") == "oops"  # type: ignore[attr-defined]
    provider: Prov = instance._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    tool_msg = provider.complete_calls[1]["messages"][-1]  # type: ignore[index]
    assert tool_msg.is_error is True
    assert "ghost" in tool_msg.content


@pytest.mark.asyncio
async def test_non_string_tool_result_is_json_stringified() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses = [
                Response(
                    text="",
                    tool_calls=[ToolCall(id="x", name="meta", arguments={})],
                    finish_reason="tool_calls",
                ),
                Response(text="done", finish_reason="stop"),
            ]

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def meta(self) -> dict[str, int]:
            """Return a dict."""
            return {"count": 3}

    instance = Demo()
    await instance.run("hi")  # type: ignore[attr-defined]
    provider: Prov = instance._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    payload = provider.complete_calls[1]["messages"][-1].content  # type: ignore[index]
    assert json.loads(payload) == {"count": 3}


# ---------------------------------------------------------------------------
# stream() — streaming loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_executes_tool_and_continues_streaming() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self._round = 0

        @override
        def stream(self, **kwargs: object):
            self.stream_calls.append(kwargs)
            self._round += 1
            if self._round == 1:
                events = [
                    Chunk(delta="thinking… "),
                    Chunk(
                        delta="",
                        tool_call_delta=ToolCallDelta(id="call_1", name="echo", index=0),
                    ),
                    Chunk(
                        delta="",
                        tool_call_delta=ToolCallDelta(
                            id="",
                            arguments_delta='{"value":"ping"}',
                            index=0,
                        ),
                    ),
                    Chunk(delta="", finish_reason="tool_calls"),
                ]
            else:
                events = [Chunk(delta="answer"), Chunk(delta="", finish_reason="stop")]

            async def _it():
                for ev in events:
                    yield ev

            return _it()

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            return value

    pieces: list[str] = []
    async for piece in Demo().stream("hi"):  # type: ignore[attr-defined]
        pieces.append(piece)
    assert pieces == ["thinking… ", "answer"]


@pytest.mark.asyncio
async def test_stream_cap_raises_agent_tool_loop_error() -> None:
    class Prov(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__()
            self._round = 0

        @override
        def stream(self, **kwargs: object):
            self.stream_calls.append(kwargs)
            self._round += 1
            events = [
                Chunk(
                    delta="",
                    tool_call_delta=ToolCallDelta(id=f"call_{self._round}", name="echo", index=0),
                ),
                Chunk(
                    delta="",
                    tool_call_delta=ToolCallDelta(id="", arguments_delta='{"value":"x"}', index=0),
                ),
                Chunk(delta="", finish_reason="tool_calls"),
            ]

            async def _it():
                for ev in events:
                    yield ev

            return _it()

    _register(Prov)

    @Agent(model="claude-sonnet-4-7", system="…", max_tool_iterations=2)
    class Demo:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo."""
            return value

    with pytest.raises(AgentToolLoopError):
        async for _ in Demo().stream("hi"):  # type: ignore[attr-defined]
            pass


# Observability coverage (execute_tool spans, gen_ai.* attrs, etc.) lives in
# tests/observability/test_tracing.py — that suite uses the OTel SDK's
# InMemorySpanExporter to assert the full span tree.
