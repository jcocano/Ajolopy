"""Errors raised by the ``ajolopy.memory`` sub-package.

All errors derive from :class:`MemoryError` so callers can catch the
framework's memory layer with a single ``except``. Subclasses signal
distinct failure modes:

- :class:`MemoryConfigError` — misconfiguration detected at resolution
  time (unknown URL scheme, malformed SQLite path).
- :class:`MemoryDependencyError` — the optional backend SDK
  (``redis``, ``asyncpg``, ``motor``) is not installed but the user
  tried to actually construct the matching backend. Carries the
  ``pip install ajolopy[<extra>]`` hint in the message.
- :class:`MemoryRuntimeError` — runtime failure interacting with the
  underlying store that did not match a more specific category.
"""


class MemoryError(RuntimeError):
    """Base class for any error raised by the ``ajolopy.memory`` layer."""


class MemoryConfigError(MemoryError):
    """Misconfiguration detected at resolution / construction time."""


class MemoryDependencyError(MemoryError):
    """The optional backend SDK is not installed.

    Raised at backend construction time so misconfigured agents fail
    fast at decoration / boot rather than on the first request.
    """


class MemoryRuntimeError(MemoryError):
    """A runtime memory operation (get, append, clear) failed."""


__all__ = [
    "MemoryConfigError",
    "MemoryDependencyError",
    "MemoryError",
    "MemoryRuntimeError",
]
