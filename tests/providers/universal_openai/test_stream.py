"""Tests for UniversalOpenAIProvider.stream().

Covers the "stream()" acceptance group: text deltas, finish_reason
mapping, cancellation, and tool-call delta accumulation (which goes
through the shared helper module reused with AJ-20).
"""

import pytest

from ajolopy.providers import Message
from ajolopy.providers.universal_openai import UniversalOpenAIProvider

from .conftest import make_async_client, make_stream_chunk


@pytest.mark.asyncio
async def test_stream_yields_text_chunks_with_prefix_stripped() -> None:
    events = [
        make_stream_chunk(text="Hi "),
        make_stream_chunk(text="there"),
        make_stream_chunk(finish_reason="stop"),
    ]
    client = make_async_client(stream_events=events)
    provider = UniversalOpenAIProvider(clients={"together": client})
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="together:meta-llama/Llama-3.3-70B-Instruct-Turbo",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert [c.delta for c in chunks[:2]] == ["Hi ", "there"]
    # The SDK call must have received the stripped model identifier.
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    assert kwargs["stream"] is True


@pytest.mark.asyncio
async def test_stream_final_chunk_carries_finish_reason() -> None:
    events = [
        make_stream_chunk(text="ok"),
        make_stream_chunk(finish_reason="stop"),
    ]
    client = make_async_client(stream_events=events)
    provider = UniversalOpenAIProvider(clients={"groq": client})
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="groq:llama-3.3-70b-versatile",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_cancellation_closes_underlying_sdk_stream() -> None:
    events = [
        make_stream_chunk(text="Hi "),
        make_stream_chunk(text="there"),
        make_stream_chunk(finish_reason="stop"),
    ]
    client = make_async_client(stream_events=events)
    provider = UniversalOpenAIProvider(clients={"groq": client})
    iterator = provider.stream(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
    )
    first = await iterator.__anext__()
    assert first.delta == "Hi "
    # The async-generator's aclose() runs the finally block that calls
    # .close() on the SDK stream object. The ABC declares
    # AsyncIterator[Chunk] which has no aclose, hence the pyright
    # ignore (mirrors the AJ-20 test).
    await iterator.aclose()  # pyright: ignore[reportAttributeAccessIssue]
    sdk_stream = client._stream_iterator
    assert sdk_stream.close_called is True


@pytest.mark.asyncio
async def test_stream_tool_call_deltas_accumulate_same_way_as_aj20() -> None:
    # The shared _openai_helpers.convert_stream_event is responsible for
    # this assembly logic; the same shape AJ-20 already pins.
    events = [
        make_stream_chunk(
            tool_call_deltas=[
                {
                    "index": 0,
                    "id": "call_1",
                    "function": {"name": "lookup_order", "arguments": ""},
                }
            ]
        ),
        make_stream_chunk(tool_call_deltas=[{"index": 0, "function": {"arguments": '{"order'}}]),
        make_stream_chunk(
            tool_call_deltas=[{"index": 0, "function": {"arguments": '_id": "X-9"}'}}]
        ),
        make_stream_chunk(finish_reason="tool_calls"),
    ]
    client = make_async_client(stream_events=events)
    provider = UniversalOpenAIProvider(clients={"groq": client})
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="groq:llama-3.3-70b-versatile",
            messages=[Message(role="user", content="find order X-9")],
        )
    ]
    first = chunks[0]
    assert first.tool_call_delta is not None
    assert first.tool_call_delta.id == "call_1"
    assert first.tool_call_delta.name == "lookup_order"
    assert first.tool_call_delta.index == 0
    fragments = [
        c.tool_call_delta.arguments_delta
        for c in chunks
        if c.tool_call_delta is not None and c.tool_call_delta.arguments_delta
    ]
    assert "".join(fragments) == '{"order_id": "X-9"}'
    assert chunks[-1].finish_reason == "tool_calls"
