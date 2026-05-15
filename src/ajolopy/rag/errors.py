"""Errors raised by the ``ajolopy.rag`` sub-package.

All errors derive from :class:`RetrieverError` so callers can catch the
framework's retrieval layer with a single ``except``. Subclasses signal
distinct failure modes:

- :class:`RetrieverConfigError` — misconfiguration detected at resolution
  or construction time (unknown URL scheme, malformed pgvector URL,
  invalid table/collection name).
- :class:`RetrieverDependencyError` — the optional backend SDK
  (``qdrant-client``, ``asyncpg`` / ``pgvector``) is not installed but
  the user tried to construct the matching backend. Carries the
  ``pip install ajolopy[<extra>]`` hint in the message.
- :class:`RetrieverRuntimeError` — runtime failure interacting with the
  underlying store (connection refused, embedding-dim mismatch, SDK
  exception during ``index`` / ``query`` / ``clear``).
"""


class RetrieverError(RuntimeError):
    """Base class for any error raised by the ``ajolopy.rag`` layer."""


class RetrieverConfigError(RetrieverError):
    """Misconfiguration detected at resolution / construction time."""


class RetrieverDependencyError(RetrieverError):
    """The optional backend SDK is not installed.

    Raised at backend construction time so misconfigured retrievers fail
    fast at decoration / boot rather than on the first ``index`` /
    ``query`` call.
    """


class RetrieverRuntimeError(RetrieverError):
    """A runtime retrieval operation (index, query, clear) failed."""


__all__ = [
    "RetrieverConfigError",
    "RetrieverDependencyError",
    "RetrieverError",
    "RetrieverRuntimeError",
]
