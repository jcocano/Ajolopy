"""Tests for `@Agent` streaming surface.

Covers the "Streaming surface" acceptance group.
"""

import pytest

from ajolopy import Agent
from ajolopy.providers import Chunk, register_provider

from .conftest import FakeProvider


class _StreamingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.stream_events = [
            Chunk(delta="Hi "),
            Chunk(delta="there"),
            Chunk(delta="", finish_reason="stop"),
        ]


@pytest.mark.asyncio
async def test_stream_yields_str_chunks() -> None:
    register_provider("anthropic", _StreamingProvider)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    instance = Demo()
    chunks: list[str] = []
    async for piece in instance.stream("hello"):  # type: ignore[attr-defined]
        chunks.append(piece)
    assert chunks == ["Hi ", "there"]


@pytest.mark.asyncio
async def test_stream_cancellation_does_not_raise() -> None:
    register_provider("anthropic", _StreamingProvider)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    instance = Demo()
    iterator = instance.stream("hello")  # type: ignore[attr-defined]
    first = await iterator.__anext__()
    assert first == "Hi "
    # aclose() is provided by async generators — the test exercises that
    # cancellation is well-behaved (no exception leaks).
    await iterator.aclose()
