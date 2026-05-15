"""Acceptance tests for :class:`RedisMemory`.

Uses ``fakeredis`` for a deterministic in-process Redis fake.
``RedisMemory`` calls ``redis.asyncio.from_url`` at construction time;
we monkeypatch that helper to return a ``fakeredis.aioredis.FakeRedis``
client so the test never touches the network and never depends on a
running Redis server.
"""

from typing import Any

import pytest

from ajolopy.memory import RedisMemory
from ajolopy.memory.errors import MemoryDependencyError
from ajolopy.providers import Message


@pytest.fixture
def fake_redis_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``redis.asyncio.from_url`` to return a fakeredis client."""
    import fakeredis.aioredis
    import redis.asyncio as redis_asyncio

    def _fake_from_url(url: str, decode_responses: bool = False) -> Any:
        return fakeredis.aioredis.FakeRedis(decode_responses=decode_responses)

    monkeypatch.setattr(redis_asyncio, "from_url", _fake_from_url)
    return _fake_from_url


@pytest.mark.asyncio
async def test_round_trip_messages(fake_redis_factory: Any) -> None:
    _ = fake_redis_factory
    memory = RedisMemory("redis://localhost:6379/0")
    await memory.append("s1", Message(role="user", content="hello"))
    await memory.append("s1", Message(role="assistant", content="hi back"))
    fetched = await memory.get("s1")
    assert [m.content for m in fetched] == ["hello", "hi back"]
    assert [m.role for m in fetched] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_prefix_namespaces_keys(fake_redis_factory: Any) -> None:
    _ = fake_redis_factory
    a = RedisMemory("redis://localhost:6379/0", prefix="appA:")
    b = RedisMemory("redis://localhost:6379/0", prefix="appB:")
    await a.append("s1", Message(role="user", content="from A"))
    await b.append("s1", Message(role="user", content="from B"))
    a_rows = await a.get("s1")
    b_rows = await b.get("s1")
    assert [m.content for m in a_rows] == ["from A"]
    assert [m.content for m in b_rows] == ["from B"]


@pytest.mark.asyncio
async def test_clear_deletes_list_key(fake_redis_factory: Any) -> None:
    _ = fake_redis_factory
    memory = RedisMemory("redis://localhost:6379/0")
    await memory.append("s1", Message(role="user", content="ephemeral"))
    await memory.clear("s1")
    assert await memory.get("s1") == []


def test_missing_extra_raises_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate missing ``redis`` extra by sabotaging the import path."""
    import builtins

    real_import = builtins.__import__

    def _patched_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "redis.asyncio" or (name == "redis" and "asyncio" in (fromlist or ())):
            raise ImportError("redis is not installed (simulated)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    with pytest.raises(MemoryDependencyError) as info:
        RedisMemory("redis://localhost:6379/0")
    assert "ajolopy[redis]" in str(info.value)
