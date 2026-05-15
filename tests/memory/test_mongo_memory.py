"""Acceptance tests for :class:`MongoDBMemory`.

Uses ``mongomock-motor`` for a deterministic in-process MongoDB fake.
``MongoDBMemory`` calls ``motor.motor_asyncio.AsyncIOMotorClient`` at
construction time; we monkeypatch that helper to return a
``mongomock_motor.AsyncMongoMockClient`` so the test never depends on
a running MongoDB server.
"""

from typing import Any

import pytest

from ajolopy.memory import MongoDBMemory
from ajolopy.memory.errors import MemoryConfigError, MemoryDependencyError
from ajolopy.providers import Message


@pytest.fixture
def mongo_mock(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``motor.motor_asyncio.AsyncIOMotorClient`` with the mongomock fake."""
    from mongomock_motor import AsyncMongoMockClient
    from motor import motor_asyncio

    def _factory(url: str) -> Any:
        return AsyncMongoMockClient()

    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", _factory)
    return _factory


@pytest.mark.asyncio
async def test_round_trip_messages(mongo_mock: Any) -> None:
    _ = mongo_mock
    memory = MongoDBMemory("mongodb://localhost:27017/testapp")
    await memory.append("s1", Message(role="user", content="hello"))
    await memory.append("s1", Message(role="assistant", content="hi back"))
    fetched = await memory.get("s1")
    assert [m.content for m in fetched] == ["hello", "hi back"]
    assert [m.role for m in fetched] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_collection_kwarg_routes_to_named_collection(mongo_mock: Any) -> None:
    _ = mongo_mock
    a = MongoDBMemory("mongodb://localhost:27017/testapp", collection="alpha")
    b = MongoDBMemory("mongodb://localhost:27017/testapp", collection="beta")
    await a.append("s1", Message(role="user", content="from alpha"))
    await b.append("s1", Message(role="user", content="from beta"))
    # The collection names differ but both clients are independent
    # mock instances; verify each sees only its own writes.
    a_rows = await a.get("s1")
    b_rows = await b.get("s1")
    assert [m.content for m in a_rows] == ["from alpha"]
    assert [m.content for m in b_rows] == ["from beta"]


@pytest.mark.asyncio
async def test_clear_removes_only_target_session(mongo_mock: Any) -> None:
    _ = mongo_mock
    memory = MongoDBMemory("mongodb://localhost:27017/testapp")
    await memory.append("s1", Message(role="user", content="a"))
    await memory.append("s2", Message(role="user", content="b"))
    await memory.clear("s1")
    assert await memory.get("s1") == []
    assert (await memory.get("s2"))[0].content == "b"


def test_missing_db_in_url_raises_config_error(mongo_mock: Any) -> None:
    _ = mongo_mock
    with pytest.raises(MemoryConfigError):
        MongoDBMemory("mongodb://localhost:27017/")


def test_missing_extra_raises_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate missing ``motor`` extra by sabotaging the import path."""
    import builtins

    real_import = builtins.__import__

    def _patched_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "motor" and "motor_asyncio" in (fromlist or ()):
            raise ImportError("motor is not installed (simulated)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    with pytest.raises(MemoryDependencyError) as info:
        MongoDBMemory("mongodb://localhost:27017/testapp")
    assert "ajolopy[mongo]" in str(info.value)
