"""SQLite-backed :class:`Memory` (stdlib ``sqlite3`` + ``asyncio.to_thread``).

Mirrors the Postgres schema (one row per appended message, ordered by
auto-incrementing primary key) but uses ``TEXT`` instead of ``JSONB``
for the message payload. The constructor only validates the path and
ensures the parent directory exists; schema creation runs idempotently
on the first ``get`` / ``append`` / ``clear`` call so the public
``__init__`` stays sync-safe (no ``await init()`` step required).

File-backed databases open a short-lived :class:`sqlite3.Connection`
per operation inside ``asyncio.to_thread`` — simple and lock-free
under concurrency at the cost of a syscall per call (acceptable for
chat-history workloads dominated by LLM round-trip latency).
``":memory:"`` databases keep a single long-lived connection
(otherwise each new connection would observe an empty database) and
serialise operations through an ``asyncio.Lock`` so concurrent
callers do not stomp on each other's writes.
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, override

from ._serde import message_from_json, message_to_json
from .base import Memory
from .errors import MemoryConfigError, MemoryRuntimeError

if TYPE_CHECKING:
    from ajolopy.providers import Message


class SQLiteMemory(Memory):
    """SQLite-backed transcript store using stdlib ``sqlite3``.

    ``path`` accepts ``":memory:"`` for an ephemeral in-process
    database (handy in tests) or a filesystem path for durable
    storage. Parent directories are created on first use if missing.

    The schema lives in a single fixed table (``ajolopy_memory``) with
    one row per appended message and an index on
    ``(session_id, id)`` for ordered playback.
    """

    _TABLE = "ajolopy_memory"
    _CREATE_SQL = (
        f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT NOT NULL, "
        "message_json TEXT NOT NULL, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    _INDEX_SQL = f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_session ON {_TABLE}(session_id, id)"

    def __init__(self, path: str) -> None:
        if not path:
            raise MemoryConfigError("SQLiteMemory requires a non-empty path.")
        self._path = path
        # ``:memory:`` databases live entirely in RAM and are scoped to a
        # single connection. We hold a long-lived connection in that case
        # so every operation observes the same database state; for file
        # paths each operation opens its own connection (simpler and
        # lock-free under concurrency).
        self._shared_conn: sqlite3.Connection | None = None
        self._schema_ready = False
        self._init_lock = asyncio.Lock()
        self._op_lock = asyncio.Lock()

    @property
    def _is_in_memory(self) -> bool:
        return self._path == ":memory:"

    def _ensure_parent_dir(self) -> None:
        # ``:memory:`` databases live entirely in RAM — nothing to create.
        if self._is_in_memory:
            return
        parent = Path(self._path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        # ``check_same_thread=False`` is safe here because every helper
        # opens its own connection inside ``asyncio.to_thread`` and the
        # connection never crosses thread boundaries within a single
        # operation.
        return sqlite3.connect(self._path, check_same_thread=False)

    def _acquire_connection(self) -> sqlite3.Connection:
        # In-memory databases must reuse the same connection so writes
        # become visible to subsequent reads; file-backed paths get a
        # fresh connection per operation.
        if self._is_in_memory:
            if self._shared_conn is None:
                self._shared_conn = self._connect()
            return self._shared_conn
        return self._connect()

    def _release_connection(self, conn: sqlite3.Connection) -> None:
        if self._is_in_memory:
            return
        conn.close()

    def _init_schema_sync(self) -> None:
        self._ensure_parent_dir()
        conn = self._acquire_connection()
        try:
            conn.execute(self._CREATE_SQL)
            conn.execute(self._INDEX_SQL)
            conn.commit()
        finally:
            self._release_connection(conn)

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._init_lock:
            if self._schema_ready:
                return
            try:
                await asyncio.to_thread(self._init_schema_sync)
            except sqlite3.Error as exc:
                raise MemoryRuntimeError(f"SQLite schema init failed: {exc}") from exc
            self._schema_ready = True

    # The three DML statements interpolate ``_TABLE`` (a hard-coded
    # class constant — no user input). ``session_id`` and the message
    # payload are always bound through sqlite3 ``?`` placeholders.
    _SELECT_SQL = f"SELECT message_json FROM {_TABLE} WHERE session_id = ? ORDER BY id"  # noqa: S608
    _INSERT_SQL = f"INSERT INTO {_TABLE}(session_id, message_json) VALUES (?, ?)"  # noqa: S608
    _DELETE_SQL = f"DELETE FROM {_TABLE} WHERE session_id = ?"  # noqa: S608

    def _get_sync(self, session_id: str) -> list[str]:
        conn = self._acquire_connection()
        try:
            cur = conn.execute(self._SELECT_SQL, (session_id,))
            rows = cur.fetchall()
        finally:
            self._release_connection(conn)
        return [str(row[0]) for row in rows]

    def _append_sync(self, session_id: str, payload: str) -> None:
        conn = self._acquire_connection()
        try:
            conn.execute(self._INSERT_SQL, (session_id, payload))
            conn.commit()
        finally:
            self._release_connection(conn)

    def _clear_sync(self, session_id: str) -> None:
        conn = self._acquire_connection()
        try:
            conn.execute(self._DELETE_SQL, (session_id,))
            conn.commit()
        finally:
            self._release_connection(conn)

    @override
    async def get(self, session_id: str) -> list[Message]:
        await self._ensure_schema()
        try:
            async with self._op_lock:
                rows = await asyncio.to_thread(self._get_sync, session_id)
        except sqlite3.Error as exc:
            raise MemoryRuntimeError(f"SQLite get() failed: {exc}") from exc
        return [message_from_json(row) for row in rows]

    @override
    async def append(self, session_id: str, message: Message) -> None:
        await self._ensure_schema()
        payload = message_to_json(message)
        try:
            async with self._op_lock:
                await asyncio.to_thread(self._append_sync, session_id, payload)
        except sqlite3.Error as exc:
            raise MemoryRuntimeError(f"SQLite append() failed: {exc}") from exc

    @override
    async def clear(self, session_id: str) -> None:
        await self._ensure_schema()
        try:
            async with self._op_lock:
                await asyncio.to_thread(self._clear_sync, session_id)
        except sqlite3.Error as exc:
            raise MemoryRuntimeError(f"SQLite clear() failed: {exc}") from exc


__all__ = ["SQLiteMemory"]
