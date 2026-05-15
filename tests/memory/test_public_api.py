"""Pin the public re-exports of :mod:`ajolopy.memory`."""

from typing import override

from ajolopy.memory import (
    InMemoryMemory,
    Memory,
    MemoryConfigError,
    MemoryDependencyError,
    MemoryError,
    MemoryRuntimeError,
    MongoDBMemory,
    PostgresMemory,
    RedisMemory,
    SQLiteMemory,
    resolve_memory,
)
from ajolopy.providers import Message


def test_public_re_exports_are_all_importable() -> None:
    assert issubclass(InMemoryMemory, Memory)
    assert issubclass(RedisMemory, Memory)
    assert issubclass(PostgresMemory, Memory)
    assert issubclass(MongoDBMemory, Memory)
    assert issubclass(SQLiteMemory, Memory)
    assert issubclass(MemoryConfigError, MemoryError)
    assert issubclass(MemoryDependencyError, MemoryError)
    assert issubclass(MemoryRuntimeError, MemoryError)
    # ``resolve_memory`` is the documented dispatcher.
    assert callable(resolve_memory)


def test_abc_cannot_be_instantiated_directly() -> None:
    import pytest

    with pytest.raises(TypeError):
        Memory()  # type: ignore[abstract]


def test_partial_subclass_remains_abstract() -> None:
    import pytest

    class Half(Memory):
        @override
        async def get(self, session_id: str) -> list[Message]:
            return []

    with pytest.raises(TypeError):
        Half()  # type: ignore[abstract]


def test_no_top_level_re_exports() -> None:
    """The Brief keeps the public top-level namespace minimal."""
    import ajolopy

    top_level = set(getattr(ajolopy, "__all__", []))
    leakers = {
        "Memory",
        "InMemoryMemory",
        "RedisMemory",
        "PostgresMemory",
        "MongoDBMemory",
        "SQLiteMemory",
        "MemoryError",
        "MemoryConfigError",
        "MemoryDependencyError",
        "MemoryRuntimeError",
        "resolve_memory",
    }
    assert leakers.isdisjoint(top_level), (
        f"Memory symbols should live under ajolopy.memory only; leaked: {leakers & top_level}"
    )
