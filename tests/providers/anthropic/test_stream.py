"""Tests for AnthropicProvider.stream().

Covers the "stream()" acceptance group: text deltas, finish_reason,
cancellation, tool-use deltas.
"""

from types import SimpleNamespace

import pytest

from ajolopy.providers import Message
from ajolopy.providers.anthropic import AnthropicProvider

from .conftest import make_async_client


@pytest.mark.asyncio
async def test_stream_yields_text_chunks_then_finish_reason() -> None:
    events = [
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="Hi "),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="there"),
        ),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="end_turn"),
        ),
    ]
    client = make_async_client(stream_events=events)
    provider = AnthropicProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="claude-sonnet-4-7",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert [c.delta for c in chunks[:2]] == ["Hi ", "there"]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_tool_use_start_emits_tool_call_delta_with_name() -> None:
    events = [
        SimpleNamespace(
            type="content_block_start",
            content_block=SimpleNamespace(type="tool_use", id="tool_1", name="lookup_order"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"id"'),
            index=0,
        ),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="tool_use"),
        ),
    ]
    client = make_async_client(stream_events=events)
    provider = AnthropicProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="claude-sonnet-4-7",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert chunks[0].tool_call_delta is not None
    assert chunks[0].tool_call_delta.name == "lookup_order"
    assert chunks[1].tool_call_delta is not None
    assert chunks[1].tool_call_delta.arguments_delta == '{"id"'
    assert chunks[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_cancellation_does_not_raise() -> None:
    events = [
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="Hi "),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="there"),
        ),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="end_turn"),
        ),
    ]
    client = make_async_client(stream_events=events)
    provider = AnthropicProvider(client=client)
    iterator = provider.stream(
        model="claude-sonnet-4-7",
        messages=[Message(role="user", content="hi")],
    )
    first = await iterator.__anext__()
    assert first.delta == "Hi "
    # Close the iterator early — the implementation is an async generator,
    # so its aclose() invokes the SDK stream's __aexit__. The ABC declares
    # AsyncIterator[Chunk] which has no aclose, hence the pyright ignore.
    await iterator.aclose()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
