"""Memory sub-package — chat-history persistence for ``@Agent``.

Public surface (re-exported here):

- :class:`Memory` — the abstract base class every backend implements.
- :class:`InMemoryMemory` — dict-backed, per-process default.
- :class:`RedisMemory` — Redis LIST per session (``ajolopy[redis]``).
- :class:`PostgresMemory` — Postgres rows per message (``ajolopy[postgres]``).
- :class:`MongoDBMemory` — MongoDB documents per message (``ajolopy[mongo]``).
- :class:`SQLiteMemory` — stdlib sqlite3 + ``asyncio.to_thread``.
- :func:`resolve_memory` — dispatches a ``memory=`` kwarg on URL scheme.
- :class:`MemoryError` and its three subclasses — the error hierarchy.

Importing this package does **not** require any optional extras —
backends import their underlying SDKs lazily inside ``__init__`` so
``MemoryDependencyError`` only fires when a backend without its
matching extra is actually instantiated.

Semantic memory / RAG (Qdrant, pgvector) lives in a sibling abstraction
tracked separately (AJ-62); this package is chat-history only.
"""

from .base import Memory
from .errors import (
    MemoryConfigError,
    MemoryDependencyError,
    MemoryError,
    MemoryRuntimeError,
)
from .in_memory import InMemoryMemory
from .mongo_memory import MongoDBMemory
from .postgres_memory import PostgresMemory
from .redis_memory import RedisMemory
from .resolver import resolve_memory
from .sqlite_memory import SQLiteMemory

__all__ = [
    "InMemoryMemory",
    "Memory",
    "MemoryConfigError",
    "MemoryDependencyError",
    "MemoryError",
    "MemoryRuntimeError",
    "MongoDBMemory",
    "PostgresMemory",
    "RedisMemory",
    "SQLiteMemory",
    "resolve_memory",
]
