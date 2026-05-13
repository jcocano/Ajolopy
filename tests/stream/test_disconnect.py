"""Mid-stream client disconnect cancels the generator."""

import asyncio
from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from ajolopy.stream.runtime import _iterate_sse


@pytest.mark.asyncio
async def test_disconnect_runs_generator_finally() -> None:
    finally_ran = False

    async def long_running() -> AsyncGenerator[str]:
        nonlocal finally_ran
        try:
            for i in range(1_000):
                yield f"chunk-{i}"
                await asyncio.sleep(0.01)
        finally:
            finally_ran = True

    request = MagicMock()
    # Flip to disconnected after the first poll succeeds.
    request.is_disconnected = AsyncMock(side_effect=[False, False, True])

    body = _iterate_sse(long_running(), None, request)
    collected: list[bytes] = []
    async for chunk in body:
        collected.append(chunk)
        if len(collected) >= 1:
            # Let the disconnect watcher catch up.
            await asyncio.sleep(0.25)

    assert finally_ran, "Generator's finally block should have run on disconnect"


@pytest.mark.asyncio
async def test_generator_aclose_called_on_consumer_break() -> None:
    closed = False

    async def gen() -> AsyncGenerator[str]:
        nonlocal closed
        try:
            while True:
                yield "tick"
                await asyncio.sleep(0.05)
        except GeneratorExit:
            closed = True
            raise
        finally:
            closed = True

    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)

    # The runtime returns the value as an ``AsyncIterator[bytes]`` for the
    # public API, but the concrete implementation is an async generator
    # whose ``aclose`` triggers the cleanup path we want to exercise.
    body = cast("AsyncGenerator[bytes]", _iterate_sse(gen(), None, request))
    aiter = body.__aiter__()
    first = await aiter.__anext__()
    assert first.startswith(b"data: tick")
    await body.aclose()
    # Give cancellations a tick to settle.
    await asyncio.sleep(0.05)
    assert closed
