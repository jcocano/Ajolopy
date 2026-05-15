"""Acceptance tests for :func:`resolve_memory`."""

from typing import Any

import pytest

from ajolopy.memory import (
    InMemoryMemory,
    Memory,
    MongoDBMemory,
    PostgresMemory,
    RedisMemory,
    SQLiteMemory,
    resolve_memory,
)
from ajolopy.memory.errors import MemoryConfigError


@pytest.fixture
def patch_optional_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out network clients so Redis / Mongo constructors stay offline."""
    import fakeredis.aioredis
    import redis.asyncio as redis_asyncio
    from mongomock_motor import AsyncMongoMockClient
    from motor import motor_asyncio

    def _fake_redis(url: str, decode_responses: bool = False) -> Any:
        return fakeredis.aioredis.FakeRedis(decode_responses=decode_responses)

    def _fake_motor(url: str) -> Any:
        return AsyncMongoMockClient()

    monkeypatch.setattr(redis_asyncio, "from_url", _fake_redis)
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", _fake_motor)


def test_none_returns_none() -> None:
    assert resolve_memory(None) is None


def test_instance_passes_through() -> None:
    instance = InMemoryMemory()
    assert resolve_memory(instance) is instance


def test_memory_subclass_is_instantiated() -> None:
    resolved = resolve_memory(InMemoryMemory)
    assert isinstance(resolved, InMemoryMemory)


def test_memory_short_form_resolves_to_in_memory() -> None:
    assert isinstance(resolve_memory("memory://"), InMemoryMemory)


def test_sqlite_in_memory_short_form() -> None:
    resolved = resolve_memory(":memory:")
    assert isinstance(resolved, SQLiteMemory)


def test_sqlite_url_extracts_path(tmp_path: Any) -> None:
    relative_url = "sqlite:///example.db"
    resolved = resolve_memory(relative_url)
    assert isinstance(resolved, SQLiteMemory)
    assert resolved._path == "example.db"

    abs_path = tmp_path / "memory.db"
    abs_url = f"sqlite:///{abs_path}"  # produces 4 slashes for an abs path
    resolved_abs = resolve_memory(abs_url)
    assert isinstance(resolved_abs, SQLiteMemory)
    assert resolved_abs._path == str(abs_path)


def test_redis_url_resolves_to_redis_memory(patch_optional_clients: None) -> None:
    _ = patch_optional_clients
    resolved = resolve_memory("redis://localhost:6379/0")
    assert isinstance(resolved, RedisMemory)


def test_postgresql_url_resolves_to_postgres_memory() -> None:
    resolved = resolve_memory("postgresql://user:pass@localhost/db")
    assert isinstance(resolved, PostgresMemory)


def test_postgres_short_url_also_resolves() -> None:
    resolved = resolve_memory("postgres://user:pass@localhost/db")
    assert isinstance(resolved, PostgresMemory)


def test_mongodb_url_resolves_to_mongo_memory(patch_optional_clients: None) -> None:
    _ = patch_optional_clients
    resolved = resolve_memory("mongodb://localhost:27017/myapp")
    assert isinstance(resolved, MongoDBMemory)


def test_unknown_scheme_raises_config_error() -> None:
    with pytest.raises(MemoryConfigError):
        resolve_memory("ftp://nope")


def test_non_string_non_memory_raises_config_error() -> None:
    with pytest.raises(MemoryConfigError):
        resolve_memory(42)


def test_invalid_sqlite_url_raises_config_error() -> None:
    with pytest.raises(MemoryConfigError):
        resolve_memory("sqlite://no-slashes")


def test_seven_url_forms_all_resolve(patch_optional_clients: None) -> None:
    """Smoke-test the seven documented URL forms in a single test."""
    _ = patch_optional_clients
    assert resolve_memory(None) is None
    assert isinstance(resolve_memory("memory://"), InMemoryMemory)
    assert isinstance(resolve_memory(":memory:"), SQLiteMemory)
    assert isinstance(resolve_memory("sqlite:///memory.db"), SQLiteMemory)
    assert isinstance(resolve_memory("redis://localhost:6379/0"), RedisMemory)
    assert isinstance(resolve_memory("postgresql://user:pass@localhost/db"), PostgresMemory)
    assert isinstance(resolve_memory("mongodb://localhost:27017/db"), MongoDBMemory)


def test_passed_instance_is_returned_unchanged() -> None:
    from typing import override

    from ajolopy.providers import Message

    class CustomMemory(Memory):
        @override
        async def get(self, session_id: str) -> list[Message]:
            return []

        @override
        async def append(self, session_id: str, message: Message) -> None: ...

        @override
        async def clear(self, session_id: str) -> None: ...

    instance = CustomMemory()
    assert resolve_memory(instance) is instance
