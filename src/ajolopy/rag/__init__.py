"""RAG retriever sub-package — semantic document search for ``@Agent``.

Public surface (re-exported here):

- :class:`Retriever` — the abstract base class every backend implements.
- :class:`Document` / :class:`RetrievalHit` — the immutable value types
  every backend speaks.
- :class:`QdrantRetriever` — Qdrant collection per corpus (``ajolopy[qdrant]``).
- :class:`PgvectorRetriever` — PostgreSQL + pgvector table per corpus
  (``ajolopy[pgvector]``).
- :func:`resolve_retriever` — dispatches a ``retriever=`` spec on URL
  scheme. Wired into :class:`Agent` post-v0.1; today users construct
  retrievers manually inside a ``@Tool``.
- :class:`RetrieverError` and its three subclasses — the error hierarchy.

Importing this package does **not** require any optional extras —
backends import their underlying SDKs lazily inside ``__init__`` so
:class:`RetrieverDependencyError` only fires when a backend without its
matching extra is actually instantiated.

Chat-history memory (Redis, Postgres, Mongo, SQLite) lives in the
sibling :mod:`ajolopy.memory` package; the two concerns deliberately do
not share a base class.
"""

from .base import Document, RetrievalHit, Retriever
from .errors import (
    RetrieverConfigError,
    RetrieverDependencyError,
    RetrieverError,
    RetrieverRuntimeError,
)
from .pgvector_retriever import PgvectorRetriever
from .qdrant_retriever import QdrantRetriever
from .resolver import resolve_retriever

__all__ = [
    "Document",
    "PgvectorRetriever",
    "QdrantRetriever",
    "RetrievalHit",
    "Retriever",
    "RetrieverConfigError",
    "RetrieverDependencyError",
    "RetrieverError",
    "RetrieverRuntimeError",
    "resolve_retriever",
]
