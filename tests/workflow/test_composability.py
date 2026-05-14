"""Composability tests: ``@Workflow`` with ``@Stream`` and run/stream parity.

Covers the "Composability with @Stream" acceptance group: a
``@Stream``-marked method on a ``@Workflow`` class mounts cleanly via
``create_app(streams=[Cls])`` and serves SSE events whose ``data:``
payload is JSON of each workflow event; calling ``wf.stream(...)``
directly yields the same dict sequence as the SSE payloads (with
framing stripped).
"""

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from ajolopy import Agent, Workflow
from ajolopy.http import Body, create_app
from ajolopy.providers import Chunk, ToolCallDelta, register_provider
from ajolopy.stream import Stream

from .conftest import ScriptedStreamProvider


def _register() -> None:
    register_provider("anthropic", ScriptedStreamProvider, overwrite=True)


def _delegate_round(tool_name: str, forwarded_message: str) -> list[Chunk]:
    return [
        Chunk(
            delta="",
            tool_call_delta=ToolCallDelta(id="c1", name=tool_name, index=0),
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


def _final_round(text: str) -> list[Chunk]:
    return [Chunk(delta=text), Chunk(delta="", finish_reason="stop")]


class _ChatRequest(BaseModel):
    message: str


def _parse_sse_data_events(body: bytes) -> list[Any]:
    """Parse the SSE response body into a list of decoded data payloads.

    Each SSE event ends with ``\\n\\n``; ``data:`` lines carry the
    payload. The body may also include keep-alive comments (``:``-only
    lines) which we filter out.
    """
    decoded: list[Any] = []
    for chunk in body.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Skip keep-alive comments (``: keepalive``).
        if all(line.startswith(":") for line in chunk.splitlines()):
            continue
        data_lines = [
            line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data:")
        ]
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        try:
            decoded.append(json.loads(payload))
        except json.JSONDecodeError:
            decoded.append(payload)
    return decoded


@pytest.mark.asyncio
async def test_workflow_stream_yields_same_dicts_as_sse_body() -> None:
    _register()

    @Agent(model="claude-sonnet-4-7", system="…")
    class Billing:
        """Billing."""

    @Workflow(coordinator="claude-sonnet-4-7", agents=[Billing])
    class Team:
        @Stream("/chat", heartbeat_seconds=None)
        async def handle(
            self, body: Annotated[_ChatRequest, Body()]
        ) -> AsyncGenerator[dict[str, Any]]:
            async for event in self.stream(body.message):  # type: ignore[attr-defined]
                yield event

    # Prime the coordinator script.
    coordinator: ScriptedStreamProvider = (
        Team._workflow_runtime._coordinator_provider  # type: ignore[attr-defined]
    )
    coordinator.stream_rounds = [_final_round("ok")]

    # Collect events via the direct stream() call.
    direct_events: list[dict[str, Any]] = []
    async for event in Team().stream("hello"):  # type: ignore[attr-defined]
        direct_events.append(dict(event))

    # Reset and collect events through the mounted SSE endpoint.
    coordinator._round_index = 0
    coordinator.stream_rounds = [_final_round("ok")]
    coordinator.stream_calls.clear()

    app = create_app(streams=[Team])
    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hello"})
        assert response.status_code == 200
        sse_events = _parse_sse_data_events(response.content)

    assert sse_events == direct_events
    # Final event in both surfaces is the terminal done payload.
    assert direct_events[-1]["type"] == "done"
    assert direct_events[-1]["text"] == "ok"


@pytest.mark.asyncio
async def test_workflow_run_equals_done_text_from_stream() -> None:
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
        _delegate_round("delegate_to_billing", "x"),
        _final_round("the answer"),
    ]

    streamed_done = ""
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        if event["type"] == "done":
            streamed_done = event["text"]

    # Reset and re-run; the provider must see the same call sequence.
    coordinator._round_index = 0
    coordinator.stream_calls.clear()
    coordinator.stream_rounds = [
        _delegate_round("delegate_to_billing", "x"),
        _final_round("the answer"),
    ]

    run_text: str = await Team().run("hi")  # type: ignore[attr-defined]
    assert streamed_done == run_text
