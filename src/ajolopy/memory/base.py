"""``Memory`` ABC consumed by ``@Agent``.

The contract is deliberately narrow: read the transcript for a
session, append a single message, and wipe a session. Richer surfaces
(slicing, pruning, summarisation, multi-session aggregation) land
post-v0.1 as separate methods that default to no-ops.

All methods are coroutines so backends are free to do I/O without
forcing the framework to grow a sync/async split. ``session_id`` is
an opaque string scoped by the caller — :class:`AgentRuntime`
currently passes a single per-agent default; richer scoping (per
HTTP user, per tenant) lives at the call site, not in the ABC.
"""

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ajolopy.providers import Message


class Memory(abc.ABC):
    """Conversation-history persistence contract."""

    @abc.abstractmethod
    async def get(self, session_id: str) -> list[Message]:
        """Return the stored messages for ``session_id`` (oldest first)."""

    @abc.abstractmethod
    async def append(self, session_id: str, message: Message) -> None:
        """Append ``message`` to the session's transcript."""

    @abc.abstractmethod
    async def clear(self, session_id: str) -> None:
        """Remove every message stored under ``session_id``."""


__all__ = ["Memory"]
