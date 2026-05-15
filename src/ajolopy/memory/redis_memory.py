"""Redis-backed :class:`Memory` implementation.

Each session maps to a single Redis ``LIST`` keyed
``<prefix><session_id>``. ``append`` calls ``RPUSH``, ``get`` calls
``LRANGE 0 -1``, and ``clear`` calls ``DEL`` — the simplest possible
mapping that covers the chat-history use case. The SDK is imported
lazily inside ``__init__`` so importing :mod:`ajolopy.memory` does
not require ``ajolopy[redis]`` to be installed; the import error is
surfaced as :class:`MemoryDependencyError` with a ``pip install``
hint at construction time.
"""

from typing import TYPE_CHECKING, Any, override

from ._serde import message_from_json, message_to_json
from .base import Memory
from .errors import MemoryDependencyError, MemoryRuntimeError

if TYPE_CHECKING:
    from ajolopy.providers import Message


_DEPENDENCY_HINT = (
    "The optional `redis` SDK is not installed. Install it with "
    "`pip install ajolopy[redis]` (or `uv add 'ajolopy[redis]'`) "
    "to use RedisMemory."
)


class RedisMemory(Memory):
    """Redis-backed transcript store using ``redis.asyncio``.

    ``url`` is a standard Redis URL (``redis://host:port/db``).
    ``prefix`` namespaces every key so multiple Ajolopy apps can
    share a single Redis instance without colliding.
    """

    def __init__(self, url: str, *, prefix: str = "ajolopy:memory:") -> None:
        try:
            import redis.asyncio as redis_asyncio
        except ImportError as exc:
            raise MemoryDependencyError(_DEPENDENCY_HINT) from exc
        self._url = url
        self._prefix = prefix
        # ``decode_responses=True`` returns ``str`` instead of ``bytes``
        # so the serde helpers can deserialise without an explicit decode
        # step.
        self._client: Any = redis_asyncio.from_url(url, decode_responses=True)

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    @override
    async def get(self, session_id: str) -> list[Message]:
        try:
            raw_list: Any = await self._client.lrange(self._key(session_id), 0, -1)
        except Exception as exc:
            raise MemoryRuntimeError(f"RedisMemory.get failed: {exc}") from exc
        if not isinstance(raw_list, list):
            return []
        return [message_from_json(str(item)) for item in raw_list]  # type: ignore[reportUnknownVariableType]

    @override
    async def append(self, session_id: str, message: Message) -> None:
        payload = message_to_json(message)
        try:
            await self._client.rpush(self._key(session_id), payload)
        except Exception as exc:
            raise MemoryRuntimeError(f"RedisMemory.append failed: {exc}") from exc

    @override
    async def clear(self, session_id: str) -> None:
        try:
            await self._client.delete(self._key(session_id))
        except Exception as exc:
            raise MemoryRuntimeError(f"RedisMemory.clear failed: {exc}") from exc


__all__ = ["RedisMemory"]
