"""Memory abstraction for ``@Agent``.

Scope for AJ-1: the ``Memory`` ABC and a minimal in-memory implementation
plus a ``resolve_memory`` factory. Concrete backends keyed off URLs
(``redis://``, ``postgres://``, …) and per-tenant sharding land in AJ-24,
which will replace the factory while keeping the ABC stable.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from ajolopy.providers import Message


class Memory(ABC):
    """Conversation persistence contract consumed by ``@Agent``.

    Implementations decide how to scope sessions (per agent instance,
    per HTTP user, per tenant). The ABC stays narrow on purpose: AJ-1 only
    needs read + append; richer surfaces (slicing, pruning, summarisation)
    can land later as separate methods that default to no-ops.
    """

    @abstractmethod
    async def get(self, session_id: str) -> list[Message]:
        """Return the stored messages for ``session_id`` (oldest first)."""

    @abstractmethod
    async def append(self, session_id: str, message: Message) -> None:
        """Append ``message`` to the session's transcript."""


class InMemoryMemory(Memory):
    """Process-local, dict-backed ``Memory`` implementation.

    Useful for tests, examples, and single-process demos. Lost on restart,
    not safe across workers — Redis / Postgres backends land in AJ-24.

    ``url`` is stored as metadata so the AJ-24 implementation can swap in a
    URL-aware backend without changing how ``@Agent(memory="...")`` is
    declared.
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url
        self._store: dict[str, list[Message]] = {}

    @override
    async def get(self, session_id: str) -> list[Message]:
        return list(self._store.get(session_id, []))

    @override
    async def append(self, session_id: str, message: Message) -> None:
        self._store.setdefault(session_id, []).append(message)


def resolve_memory(
    spec: str | dict[str, object] | type[Memory] | Memory | None,
) -> Memory | None:
    """Turn a ``memory=`` kwarg from ``@Agent`` into a ``Memory`` instance.

    Resolution table:

    - ``None`` → ``None`` (no memory is configured; agent runs stateless).
    - ``str`` (URL) → ``InMemoryMemory(url=str)`` for now. AJ-24 will
      parse the scheme (``redis://``, ``postgres://``) and pick the matching
      backend. The URL is preserved so the upgrade is observation-only.
    - ``dict`` → ``InMemoryMemory`` with the dict stashed for AJ-24 to
      consume (e.g. ``{"backend": "redis", "url": "...", "tenant_id": "..."}``).
    - ``type[Memory]`` → instantiate the subclass via its zero-arg
      constructor. Subclasses needing config should expose factory methods.
    - ``Memory`` instance → return as-is, for advanced cases where the
      caller wants full control of construction.
    """
    if spec is None:
        return None
    if isinstance(spec, Memory):
        return spec
    # pyright sees the union narrowed to (type[Memory] | dict | str) by here,
    # but at runtime callers can pass any object. Keep the defensive checks.
    if isinstance(spec, type) and issubclass(spec, Memory):  # pyright: ignore[reportUnnecessaryIsInstance]
        return spec()
    if isinstance(spec, str):
        return InMemoryMemory(url=spec)
    if isinstance(spec, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        return InMemoryMemory(url=str(spec.get("url", "")) or None)
    raise TypeError(
        f"Unsupported memory spec {spec!r}. Expected str URL, dict, "
        f"Memory subclass, Memory instance, or None."
    )
