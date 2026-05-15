"""PostgreSQL-backed :class:`Memory` implementation.

Uses ``asyncpg`` with a connection pool created lazily on first
operation (constructors stay sync). The schema (one row per appended
message, JSONB payload, index on ``(session_id, id)``) is created
idempotently on first use via ``CREATE TABLE IF NOT EXISTS`` so the
backend is safe against repeated process starts and concurrent
writers.

The ``mcp.client`` precedent is mirrored for the optional-extra
contract: importing :mod:`ajolopy.memory` does not require
``ajolopy[postgres]`` to be installed. ``asyncpg`` is imported
lazily inside ``__init__`` so a missing extra surfaces immediately as
:class:`MemoryDependencyError` with a ``pip install`` hint.
"""

import asyncio
import re
from typing import TYPE_CHECKING, Any, override

from ._serde import message_from_json, message_to_json
from .base import Memory
from .errors import MemoryConfigError, MemoryDependencyError, MemoryRuntimeError

if TYPE_CHECKING:
    from ajolopy.providers import Message


_DEPENDENCY_HINT = (
    "The optional `asyncpg` SDK is not installed. Install it with "
    "`pip install ajolopy[postgres]` (or `uv add 'ajolopy[postgres]'`) "
    "to use PostgresMemory."
)

# Allow letters, digits, underscore, and an optional schema qualifier so
# users can write ``my_schema.ajolopy_memory`` without opening the door
# to SQL injection through the ``table=`` kwarg.
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


class PostgresMemory(Memory):
    """PostgreSQL-backed transcript store using ``asyncpg``.

    ``url`` is a standard ``postgresql://user:pass@host/db`` connection
    string. ``table`` is the destination table name; the default is
    ``ajolopy_memory``. Subclasses (or callers using the kwarg) can
    target a different table per app — names are validated against a
    conservative whitespace/punctuation-free regex to keep the
    parameter safe to interpolate into DDL/DML.
    """

    def __init__(self, url: str, *, table: str = "ajolopy_memory") -> None:
        if not _TABLE_NAME_RE.fullmatch(table):
            raise MemoryConfigError(
                f"Invalid Postgres table name {table!r}: must match {_TABLE_NAME_RE.pattern}."
            )
        try:
            import asyncpg
        except ImportError as exc:
            raise MemoryDependencyError(_DEPENDENCY_HINT) from exc
        self._url = url
        self._table = table
        self._asyncpg: Any = asyncpg
        self._pool: Any = None
        self._schema_ready = False
        self._init_lock = asyncio.Lock()

    @property
    def _index_name(self) -> str:
        # Replace dots in qualified table names so the generated index
        # name stays a single valid identifier.
        return f"idx_{self._table.replace('.', '_')}_session"

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            try:
                self._pool = await self._asyncpg.create_pool(self._url)
            except Exception as exc:
                raise MemoryRuntimeError(
                    f"PostgresMemory could not connect to {self._url!r}: {exc}"
                ) from exc
        return self._pool

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._init_lock:
            if self._schema_ready:
                return
            pool = await self._ensure_pool()
            create_sql = (
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "id BIGSERIAL PRIMARY KEY, "
                "session_id TEXT NOT NULL, "
                "message_json JSONB NOT NULL, "
                "created_at TIMESTAMPTZ DEFAULT NOW())"
            )
            index_sql = (
                f"CREATE INDEX IF NOT EXISTS {self._index_name} ON {self._table}(session_id, id)"
            )
            try:
                async with pool.acquire() as conn:
                    await conn.execute(create_sql)
                    await conn.execute(index_sql)
            except Exception as exc:
                raise MemoryRuntimeError(f"PostgresMemory schema init failed: {exc}") from exc
            self._schema_ready = True

    @override
    async def get(self, session_id: str) -> list[Message]:
        await self._ensure_schema()
        # ``self._table`` is validated against ``_TABLE_NAME_RE`` in
        # ``__init__`` (letters / digits / underscore plus an optional
        # ``schema.table`` qualifier), so the f-string interpolation
        # cannot smuggle a SQL fragment. The ``session_id`` value is
        # always bound through asyncpg's $1 placeholder.
        sql = (
            f"SELECT message_json::text AS message_json FROM {self._table} "  # noqa: S608
            "WHERE session_id = $1 ORDER BY id"
        )
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                rows: Any = await conn.fetch(sql, session_id)
        except Exception as exc:
            raise MemoryRuntimeError(f"PostgresMemory.get failed: {exc}") from exc
        return [message_from_json(str(row["message_json"])) for row in rows]

    @override
    async def append(self, session_id: str, message: Message) -> None:
        await self._ensure_schema()
        payload = message_to_json(message)
        # Table name is regex-validated at construction (see ``get``).
        sql = f"INSERT INTO {self._table}(session_id, message_json) VALUES ($1, $2::jsonb)"  # noqa: S608
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(sql, session_id, payload)
        except Exception as exc:
            raise MemoryRuntimeError(f"PostgresMemory.append failed: {exc}") from exc

    @override
    async def clear(self, session_id: str) -> None:
        await self._ensure_schema()
        # Table name is regex-validated at construction (see ``get``).
        sql = f"DELETE FROM {self._table} WHERE session_id = $1"  # noqa: S608
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(sql, session_id)
        except Exception as exc:
            raise MemoryRuntimeError(f"PostgresMemory.clear failed: {exc}") from exc


__all__ = ["PostgresMemory"]
