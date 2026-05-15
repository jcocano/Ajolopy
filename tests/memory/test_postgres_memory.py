"""Acceptance tests for :class:`PostgresMemory`.

There is no mature in-process ``asyncpg`` fake (the SDK speaks the
PostgreSQL wire protocol end-to-end), so the deterministic coverage
here focuses on:

- Constructor validation (table-name regex, missing extra).
- Connection-error surface (an unreachable URL raises
  :class:`MemoryRuntimeError` on first use).
- A real-Postgres round-trip guarded behind ``AJOLOPY_TEST_PG_URL`` —
  CI does not set this env var; local maintainers set it to verify
  end-to-end behaviour against a real database.
"""

import os
from typing import Any

import pytest

from ajolopy.memory import PostgresMemory
from ajolopy.memory.errors import (
    MemoryConfigError,
    MemoryDependencyError,
    MemoryRuntimeError,
)
from ajolopy.providers import Message

_POSTGRES_URL = os.getenv("AJOLOPY_TEST_PG_URL")
_REQUIRES_REAL_PG = pytest.mark.skipif(
    _POSTGRES_URL is None,
    reason="Set AJOLOPY_TEST_PG_URL to run PostgresMemory integration tests.",
)


def test_default_table_constructor_succeeds() -> None:
    # Construction should never reach the DB — just bind config.
    memory = PostgresMemory("postgresql://user:pass@localhost/db")
    assert memory._table == "ajolopy_memory"


def test_custom_table_kwarg_is_accepted() -> None:
    memory = PostgresMemory(
        "postgresql://user:pass@localhost/db",
        table="custom_table",
    )
    assert memory._table == "custom_table"


def test_invalid_table_name_raises_config_error() -> None:
    with pytest.raises(MemoryConfigError):
        PostgresMemory(
            "postgresql://user:pass@localhost/db",
            table="evil; DROP TABLE users; --",
        )


def test_missing_extra_raises_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate missing ``asyncpg`` extra by sabotaging the import path."""
    import builtins

    real_import = builtins.__import__

    def _patched_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "asyncpg":
            raise ImportError("asyncpg is not installed (simulated)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    with pytest.raises(MemoryDependencyError) as info:
        PostgresMemory("postgresql://user:pass@localhost/db")
    assert "ajolopy[postgres]" in str(info.value)


@pytest.mark.asyncio
async def test_unreachable_url_raises_runtime_error() -> None:
    # 0.0.0.0:1 is reserved as an invalid endpoint; asyncpg surfaces a
    # connection refused / OS error. ``PostgresMemory`` wraps it as
    # :class:`MemoryRuntimeError` so callers can catch on a single type.
    memory = PostgresMemory("postgresql://user:pass@127.0.0.1:1/postgres")
    with pytest.raises(MemoryRuntimeError):
        await memory.get("s1")


@_REQUIRES_REAL_PG
@pytest.mark.asyncio
async def test_round_trip_against_real_postgres() -> None:
    assert _POSTGRES_URL is not None
    memory = PostgresMemory(_POSTGRES_URL, table="ajolopy_memory_test")
    await memory.clear("s_round_trip")
    await memory.append("s_round_trip", Message(role="user", content="hello"))
    await memory.append("s_round_trip", Message(role="assistant", content="hi back"))
    rows = await memory.get("s_round_trip")
    assert [m.content for m in rows] == ["hello", "hi back"]
    await memory.clear("s_round_trip")


@_REQUIRES_REAL_PG
@pytest.mark.asyncio
async def test_schema_idempotent_on_second_construction() -> None:
    assert _POSTGRES_URL is not None
    first = PostgresMemory(_POSTGRES_URL, table="ajolopy_memory_test_idem")
    await first.append("s1", Message(role="user", content="first"))
    second = PostgresMemory(_POSTGRES_URL, table="ajolopy_memory_test_idem")
    await second.append("s1", Message(role="user", content="second"))
    rows = await second.get("s1")
    assert [m.content for m in rows] == ["first", "second"]
    await second.clear("s1")
