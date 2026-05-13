"""Direct in-process usage — ``@Stream`` does not block native Python calls."""

import inspect
from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from pydantic import BaseModel

from ajolopy.http import Body
from ajolopy.stream import Stream


class _Msg(BaseModel):
    message: str


@pytest.mark.asyncio
async def test_direct_call_returns_async_generator() -> None:
    class Host:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Msg, Body()]) -> AsyncGenerator[str]:
            yield "a"
            yield "b"

    instance = Host()
    gen = instance.respond(body=_Msg(message="ignored"))
    assert inspect.isasyncgen(gen)

    collected: list[str] = []
    async for chunk in gen:
        collected.append(chunk)
    assert collected == ["a", "b"]


@pytest.mark.asyncio
async def test_plain_class_without_agent_still_works() -> None:
    class Plain:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self) -> AsyncGenerator[str]:
            yield "raw"

    instance = Plain()
    gen = instance.respond()
    chunks = [c async for c in gen]
    assert chunks == ["raw"]
