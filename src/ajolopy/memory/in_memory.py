"""In-process, dict-backed :class:`Memory` implementation."""

from typing import TYPE_CHECKING, override

from .base import Memory

if TYPE_CHECKING:
    from ajolopy.providers import Message


class InMemoryMemory(Memory):
    """Process-local ``dict[str, list[Message]]`` :class:`Memory`.

    Per-instance isolation: two ``InMemoryMemory()`` instances do not
    share state. Lost on restart and not safe across worker processes;
    use a persistent backend (Redis / Postgres / Mongo / SQLite) for
    production deployments.

    Useful for tests, examples, and single-process demos. Acts as the
    default when ``@Agent(memory=None)``.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[Message]] = {}

    @override
    async def get(self, session_id: str) -> list[Message]:
        return list(self._store.get(session_id, []))

    @override
    async def append(self, session_id: str, message: Message) -> None:
        self._store.setdefault(session_id, []).append(message)

    @override
    async def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)


__all__ = ["InMemoryMemory"]
