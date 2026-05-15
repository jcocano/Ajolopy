"""Acceptance tests for :class:`InMemoryMemory`."""

import pytest

from ajolopy.memory import InMemoryMemory
from ajolopy.providers import Message


@pytest.mark.asyncio
async def test_fresh_session_returns_empty_list() -> None:
    memory = InMemoryMemory()
    assert await memory.get("s1") == []


@pytest.mark.asyncio
async def test_append_then_get_returns_message() -> None:
    memory = InMemoryMemory()
    message = Message(role="user", content="hi")
    await memory.append("s1", message)
    fetched = await memory.get("s1")
    assert len(fetched) == 1
    assert fetched[0].content == "hi"
    assert fetched[0].role == "user"


@pytest.mark.asyncio
async def test_sessions_are_isolated() -> None:
    memory = InMemoryMemory()
    await memory.append("s1", Message(role="user", content="hi from s1"))
    await memory.append("s2", Message(role="user", content="hi from s2"))
    assert (await memory.get("s1"))[0].content == "hi from s1"
    assert (await memory.get("s2"))[0].content == "hi from s2"


@pytest.mark.asyncio
async def test_clear_only_affects_target_session() -> None:
    memory = InMemoryMemory()
    await memory.append("s1", Message(role="user", content="a"))
    await memory.append("s2", Message(role="user", content="b"))
    await memory.clear("s1")
    assert await memory.get("s1") == []
    assert (await memory.get("s2"))[0].content == "b"


@pytest.mark.asyncio
async def test_two_instances_are_independent() -> None:
    a = InMemoryMemory()
    b = InMemoryMemory()
    await a.append("s1", Message(role="user", content="hi"))
    assert await a.get("s1") != []
    assert await b.get("s1") == []
