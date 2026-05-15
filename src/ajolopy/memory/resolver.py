"""URL-based dispatch for ``@Agent(memory=...)``.

The resolver turns the ``memory=`` kwarg from :func:`Agent` into a
concrete :class:`Memory` instance (or ``None``). The mapping is
deliberately small — the killer-demo expects a one-liner URL to "just
work":

================================== ============================================
Form                               Resolution
================================== ============================================
``None``                           ``None`` (agent runs stateless)
``Memory`` instance                Returned verbatim
``"redis://..."``                  :class:`RedisMemory`
``"postgresql://..."`` / ``"postgres://..."``  :class:`PostgresMemory`
``"mongodb://..."``                :class:`MongoDBMemory`
``"sqlite:///path"``               :class:`SQLiteMemory`
``"memory://"`` / ``":memory:"``   :class:`InMemoryMemory` / in-memory SQLite
Anything else                      :class:`MemoryConfigError`
================================== ============================================

``:memory:`` (short form) routes to a :class:`SQLiteMemory` because
that is the canonical SQLite shorthand; ``memory://`` routes to
:class:`InMemoryMemory` (the dict-backed, per-instance default).
"""

from .base import Memory
from .errors import MemoryConfigError
from .in_memory import InMemoryMemory
from .mongo_memory import MongoDBMemory
from .postgres_memory import PostgresMemory
from .redis_memory import RedisMemory
from .sqlite_memory import SQLiteMemory


def _resolve_sqlite_url(url: str) -> SQLiteMemory:
    # SQLAlchemy convention: ``sqlite:///`` (3 slashes) is a relative
    # path; ``sqlite:////`` (4 slashes) is an absolute path. The first
    # ``//`` belongs to the URL grammar and the third / fourth slash is
    # the path separator. ``urlsplit`` does not parse this correctly so
    # do the slicing by hand.
    if not url.startswith("sqlite:///"):
        raise MemoryConfigError(
            f"Invalid SQLite URL {url!r}. Expected ``sqlite:///path/to/file.db``."
        )
    path = url.removeprefix("sqlite:///")
    if not path:
        raise MemoryConfigError(
            "SQLite URL is missing a path. Use ``sqlite:///path/to/file.db`` or ``:memory:``."
        )
    return SQLiteMemory(path)


def resolve_memory(spec: object) -> Memory | None:
    """Turn a ``memory=`` kwarg into a :class:`Memory` instance.

    See the module docstring for the full mapping. Unsupported specs
    raise :class:`MemoryConfigError` so misconfigured agents fail
    fast at decoration / boot time rather than at first request.
    """
    if spec is None:
        return None
    if isinstance(spec, Memory):
        return spec
    if isinstance(spec, type) and issubclass(spec, Memory):
        return spec()
    if not isinstance(spec, str):
        raise MemoryConfigError(
            f"Unsupported memory spec {spec!r}. Expected URL string, Memory instance, "
            f"Memory subclass, or None."
        )
    url = spec
    if url == ":memory:":
        return SQLiteMemory(":memory:")
    if url == "memory://":
        return InMemoryMemory()
    if url.startswith("redis://") or url.startswith("rediss://"):
        return RedisMemory(url)
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return PostgresMemory(url)
    if url.startswith("mongodb://") or url.startswith("mongodb+srv://"):
        return MongoDBMemory(url)
    if url.startswith("sqlite://"):
        return _resolve_sqlite_url(url)
    raise MemoryConfigError(
        f"Unknown memory URL scheme {url!r}. Supported: redis://, postgresql://, "
        f"mongodb://, sqlite:///, memory://, :memory:."
    )


__all__ = ["resolve_memory"]
