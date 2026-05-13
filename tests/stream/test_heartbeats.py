"""Heartbeat interleaving with user-produced events."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ajolopy.stream.runtime import _iterate_sse


def _request_never_disconnects() -> MagicMock:
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    return request


@pytest.mark.asyncio
async def test_heartbeat_interleaves_between_slow_yields() -> None:
    async def slow() -> AsyncGenerator[str]:
        # Two yields ~0.18s apart; with 0.05s heartbeat we expect ≥2 keepalive
        # comments between them.
        yield "first"
        await asyncio.sleep(0.18)
        yield "second"

    chunks = await _drain(_iterate_sse(slow(), 0.05, _request_never_disconnects()))
    joined = b"".join(chunks)
    assert b"data: first\n\n" in joined
    assert b"data: second\n\n" in joined
    assert joined.count(b": keepalive\n\n") >= 2


@pytest.mark.asyncio
async def test_heartbeat_none_emits_zero_keepalives() -> None:
    async def slow() -> AsyncGenerator[str]:
        yield "first"
        await asyncio.sleep(0.2)
        yield "second"

    chunks = await _drain(_iterate_sse(slow(), None, _request_never_disconnects()))
    joined = b"".join(chunks)
    assert joined.count(b": keepalive\n\n") == 0


@pytest.mark.asyncio
async def test_heartbeat_stops_after_generator_finishes() -> None:
    async def quick() -> AsyncGenerator[str]:
        yield "only"

    # Wait long enough that heartbeats would fire if the loop hadn't exited.
    chunks = await _drain(_iterate_sse(quick(), 0.05, _request_never_disconnects()))
    joined = b"".join(chunks)
    # The final chunk in the stream is the data event; no trailing keepalives.
    assert joined.endswith(b"data: only\n\n")
    assert joined.count(b": keepalive\n\n") == 0


async def _drain(it: AsyncIterator[bytes]) -> list[Any]:
    return [chunk async for chunk in it]
