"""MongoDB-backed :class:`Memory` implementation.

Uses ``motor`` (the async wrapper around ``pymongo``). Each appended
message becomes a single document of shape
``{session_id, message_json, created_at}``. The collection is created
implicitly by MongoDB on first write; the
``(session_id, created_at)`` index is created idempotently on first
use so playback order is stable.

The database name is taken from the URL path component
(``mongodb://host/<db>``). Empty / missing database names surface as
:class:`MemoryConfigError` so misconfigured URLs fail at construction
time rather than at first operation.
"""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, override
from urllib.parse import urlsplit

from ._serde import message_from_json, message_to_json
from .base import Memory
from .errors import MemoryConfigError, MemoryDependencyError, MemoryRuntimeError

if TYPE_CHECKING:
    from ajolopy.providers import Message


_DEPENDENCY_HINT = (
    "The optional `motor` SDK is not installed. Install it with "
    "`pip install ajolopy[mongo]` (or `uv add 'ajolopy[mongo]'`) to "
    "use MongoDBMemory."
)


def _database_from_url(url: str) -> str:
    parsed = urlsplit(url)
    # ``urlsplit`` keeps the leading slash; strip it and drop anything
    # after a ``?`` query string. The default-authsource ``/<db>``
    # pattern is what MongoDB drivers themselves consume.
    db = parsed.path.lstrip("/")
    if "?" in db:
        db = db.split("?", 1)[0]
    if not db:
        raise MemoryConfigError(
            f"MongoDB URL {url!r} is missing a database name (mongodb://host/<db>)."
        )
    return db


class MongoDBMemory(Memory):
    """MongoDB-backed transcript store using ``motor.motor_asyncio``.

    ``url`` is a standard MongoDB URL (``mongodb://host/<db>``).
    ``collection`` is the destination collection name; the default is
    ``ajolopy_memory``. Index creation is idempotent and runs once on
    first ``get`` / ``append`` / ``clear`` call.
    """

    def __init__(self, url: str, *, collection: str = "ajolopy_memory") -> None:
        if not collection:
            raise MemoryConfigError("MongoDBMemory requires a non-empty collection name.")
        try:
            from motor import motor_asyncio
        except ImportError as exc:
            raise MemoryDependencyError(_DEPENDENCY_HINT) from exc
        self._url = url
        self._database_name = _database_from_url(url)
        self._collection_name = collection
        # ``AsyncIOMotorClient`` lazily connects on first operation, so
        # the constructor stays sync-safe.
        self._client: Any = motor_asyncio.AsyncIOMotorClient(url)
        self._db: Any = self._client[self._database_name]
        self._collection: Any = self._db[self._collection_name]
        self._index_ready = False
        self._init_lock = asyncio.Lock()

    async def _ensure_index(self) -> None:
        if self._index_ready:
            return
        async with self._init_lock:
            if self._index_ready:
                return
            try:
                await self._collection.create_index(
                    [("session_id", 1), ("created_at", 1)],
                    name="session_created_idx",
                )
            except Exception as exc:
                raise MemoryRuntimeError(f"MongoDBMemory index init failed: {exc}") from exc
            self._index_ready = True

    @override
    async def get(self, session_id: str) -> list[Message]:
        await self._ensure_index()
        try:
            cursor: Any = self._collection.find({"session_id": session_id}).sort("created_at", 1)
            docs: Any = await cursor.to_list(length=None)
        except Exception as exc:
            raise MemoryRuntimeError(f"MongoDBMemory.get failed: {exc}") from exc
        out: list[Message] = []
        if not isinstance(docs, list):
            return out
        for doc_any in docs:  # type: ignore[reportUnknownVariableType]
            if not isinstance(doc_any, dict):
                continue
            payload_any: Any = doc_any.get("message_json")  # type: ignore[reportUnknownMemberType]
            if isinstance(payload_any, str):
                out.append(message_from_json(payload_any))
        return out

    @override
    async def append(self, session_id: str, message: Message) -> None:
        await self._ensure_index()
        document = {
            "session_id": session_id,
            "message_json": message_to_json(message),
            "created_at": datetime.now(UTC),
        }
        try:
            await self._collection.insert_one(document)
        except Exception as exc:
            raise MemoryRuntimeError(f"MongoDBMemory.append failed: {exc}") from exc

    @override
    async def clear(self, session_id: str) -> None:
        await self._ensure_index()
        try:
            await self._collection.delete_many({"session_id": session_id})
        except Exception as exc:
            raise MemoryRuntimeError(f"MongoDBMemory.clear failed: {exc}") from exc


__all__ = ["MongoDBMemory"]
