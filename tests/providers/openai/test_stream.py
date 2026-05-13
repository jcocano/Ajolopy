"""Tests for OpenAIProvider.stream().

Covers the "stream()" acceptance group: text deltas, finish_reason,
cancellation, tool-call deltas.
"""

import pytest

from ajolopy.providers import Message
from ajolopy.providers.openai import OpenAIProvider

from .conftest import make_async_client, make_stream_chunk


@pytest.mark.asyncio
async def test_stream_yields_text_chunks_then_finish_reason() -> None:
    events = [
        make_stream_chunk(text="Hi "),
        make_stream_chunk(text="there"),
        make_stream_chunk(finish_reason="stop"),
    ]
    client = make_async_client(stream_events=events)
    provider = OpenAIProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert [c.delta for c in chunks[:2]] == ["Hi ", "there"]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_tool_call_deltas_surface() -> None:
    events = [
        # First chunk: tool-call start with id and name.
        make_stream_chunk(
            tool_call_deltas=[
                {
                    "index": 0,
                    "id": "call_1",
                    "function": {"name": "lookup_order", "arguments": ""},
                }
            ]
        ),
        # Subsequent chunks: argument fragments without id/name.
        make_stream_chunk(tool_call_deltas=[{"index": 0, "function": {"arguments": '{"order'}}]),
        make_stream_chunk(
            tool_call_deltas=[{"index": 0, "function": {"arguments": '_id": "X-9"}'}}]
        ),
        make_stream_chunk(finish_reason="tool_calls"),
    ]
    client = make_async_client(stream_events=events)
    provider = OpenAIProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="find order X-9")],
        )
    ]
    # First emitted chunk carries the id+name.
    first = chunks[0]
    assert first.tool_call_delta is not None
    assert first.tool_call_delta.id == "call_1"
    assert first.tool_call_delta.name == "lookup_order"
    assert first.tool_call_delta.index == 0
    # Argument fragments accumulate across chunks.
    fragments = [
        c.tool_call_delta.arguments_delta
        for c in chunks
        if c.tool_call_delta is not None and c.tool_call_delta.arguments_delta
    ]
    assert "".join(fragments) == '{"order_id": "X-9"}'
    # Terminal chunk maps OpenAI's tool_calls finish reason.
    assert chunks[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_cancellation_closes_underlying_sdk_stream() -> None:
    events = [
        make_stream_chunk(text="Hi "),
        make_stream_chunk(text="there"),
        make_stream_chunk(finish_reason="stop"),
    ]
    client = make_async_client(stream_events=events)
    provider = OpenAIProvider(client=client)
    iterator = provider.stream(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="hi")],
    )
    first = await iterator.__anext__()
    assert first.delta == "Hi "
    # Close the iterator early — the implementation is an async generator,
    # so its aclose() runs the finally block which calls SDK stream.close().
    # The ABC declares AsyncIterator[Chunk] which has no aclose, hence the
    # pyright ignore (mirrors the Anthropic test).
    await iterator.aclose()  # pyright: ignore[reportAttributeAccessIssue]
    # The conftest helper records close_called=True when the provider
    # calls .close() on the SDK stream.
    sdk_stream = client._stream_iterator
    assert sdk_stream.close_called is True
