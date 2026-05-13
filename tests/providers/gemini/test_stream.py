"""Tests for GeminiProvider.stream().

Covers the "stream()" acceptance group: text deltas, finish_reason
mapping, cancellation, tool-call delta surfacing, the safety/refusal
path that terminates the iterator cleanly, and the SDK-error-mid-stream
path that surfaces as a typed framework error.
"""

import json
import logging

import pytest
from google.genai import errors as genai_errors

from ajolopy.providers import Message
from ajolopy.providers.gemini import GeminiProvider, GeminiProviderError

from .conftest import make_async_client, make_stream_chunk


@pytest.mark.asyncio
async def test_stream_yields_text_chunks_then_finish_reason() -> None:
    events = [
        make_stream_chunk(text="Hi "),
        make_stream_chunk(text="there"),
        make_stream_chunk(finish_reason="STOP"),
    ]
    client = make_async_client(stream_events=events)
    provider = GeminiProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert [c.delta for c in chunks[:2]] == ["Hi ", "there"]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_max_tokens_maps_to_length() -> None:
    events = [
        make_stream_chunk(text="Hi"),
        make_stream_chunk(finish_reason="MAX_TOKENS"),
    ]
    client = make_async_client(stream_events=events)
    provider = GeminiProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
            max_tokens=2,
        )
    ]
    assert chunks[-1].finish_reason == "length"


@pytest.mark.asyncio
async def test_stream_tool_call_surfaces_in_one_chunk() -> None:
    # Gemini emits the function call in a single chunk, not progressively.
    events = [
        make_stream_chunk(
            function_calls=[{"id": "call_1", "name": "lookup_order", "args": {"order_id": "X-9"}}]
        ),
        make_stream_chunk(finish_reason="STOP"),
    ]
    client = make_async_client(stream_events=events)
    provider = GeminiProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="find order X-9")],
        )
    ]
    first = chunks[0]
    assert first.tool_call_delta is not None
    assert first.tool_call_delta.id == "call_1"
    assert first.tool_call_delta.name == "lookup_order"
    # Whole payload comes in one delta — not a JSON fragment, the full dict.
    assert first.tool_call_delta.arguments_delta is not None
    assert json.loads(first.tool_call_delta.arguments_delta) == {"order_id": "X-9"}


@pytest.mark.asyncio
async def test_stream_cancellation_closes_underlying_sdk_stream() -> None:
    events = [
        make_stream_chunk(text="Hi "),
        make_stream_chunk(text="there"),
        make_stream_chunk(finish_reason="STOP"),
    ]
    client = make_async_client(stream_events=events)
    provider = GeminiProvider(client=client)
    iterator = provider.stream(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="hi")],
    )
    first = await iterator.__anext__()
    assert first.delta == "Hi "
    # Close the iterator early — the implementation is an async generator,
    # so its aclose() runs the finally block which calls aclose() on the
    # SDK stream. The ABC declares AsyncIterator[Chunk] which has no
    # aclose, hence the pyright ignore (mirrors the OpenAI/Anthropic tests).
    await iterator.aclose()  # pyright: ignore[reportAttributeAccessIssue]
    sdk_stream = client._stream_iterator
    assert sdk_stream.aclose_called is True


@pytest.mark.asyncio
async def test_stream_safety_finish_reason_terminates_cleanly_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events = [
        make_stream_chunk(text="partial"),
        make_stream_chunk(finish_reason="SAFETY"),
    ]
    client = make_async_client(stream_events=events)
    provider = GeminiProvider(client=client)
    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.gemini"):
        chunks = [
            chunk
            async for chunk in provider.stream(
                model="gemini-2.5-flash",
                messages=[
                    Message(role="user", content="risky"),
                ],
            )
        ]
    # Final chunk maps the refusal to "error" with delta="".
    assert chunks[-1].finish_reason == "error"
    assert chunks[-1].delta == ""
    # Provider logs the underlying reason so it's discoverable.
    assert any("SAFETY" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("refusal", ["RECITATION", "OTHER"])
@pytest.mark.asyncio
async def test_stream_refusal_variants_surface_as_error(refusal: str) -> None:
    events = [
        make_stream_chunk(text="partial"),
        make_stream_chunk(finish_reason=refusal),
    ]
    client = make_async_client(stream_events=events)
    provider = GeminiProvider(client=client)
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
        )
    ]
    assert chunks[-1].finish_reason == "error"


@pytest.mark.asyncio
async def test_stream_sdk_error_mid_stream_surfaces_as_provider_error() -> None:
    # An SDK error raised mid-stream (NOT a user cancellation) must surface
    # as a typed GeminiProviderError on the offending step.
    sdk_exc = genai_errors.APIError(code=500, response_json={"error": {"message": "internal"}})
    events = [make_stream_chunk(text="partial")]
    client = make_async_client(stream_events=events, stream_raise_after=sdk_exc)
    provider = GeminiProvider(client=client)
    iterator = provider.stream(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="hi")],
    )
    first = await iterator.__anext__()
    assert first.delta == "partial"
    with pytest.raises(GeminiProviderError, match="Gemini SDK error"):
        await iterator.__anext__()
    # Best-effort: the finally block in the generator runs and closes the
    # underlying iterator so we do not leak HTTP sockets.
    sdk_stream = client._stream_iterator
    assert sdk_stream.aclose_called is True
