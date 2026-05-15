"""URL-based dispatch for the retriever layer.

The resolver turns a ``spec`` (URL string, :class:`Retriever` instance,
:class:`Retriever` subclass, or ``None``) into a concrete
:class:`Retriever` instance (or ``None``). Unlike
:func:`ajolopy.memory.resolve_memory`, this entry point is *not* wired
into :class:`Agent` for v0.1 — users still construct retrievers
manually inside a ``@Tool``. The function exists so the framework has a
single place to add the ``@Agent(retriever=...)`` kwarg in v0.2 and so
``embedding_model`` resolution stays out of the URL grammar.

================================================ ===============================
Form                                             Resolution
================================================ ===============================
``None``                                         ``None``
``Retriever`` instance                           Returned verbatim
``Retriever`` subclass                           ``Retriever()`` (errors propagate)
``"qdrant://host:port/collection"``              :class:`QdrantRetriever`
``"pgvector://user:pass@host/db?table=x"``       :class:`PgvectorRetriever`
Anything else                                    :class:`RetrieverConfigError`
================================================ ===============================

The two URL schemes require an ``embedding_model`` — see the docstring
of :func:`resolve_retriever` for the kwarg contract.
"""

from .base import Retriever
from .errors import RetrieverConfigError


def resolve_retriever(
    spec: object,
    *,
    embedding_model: str | None = None,
) -> Retriever | None:
    """Turn a ``retriever=`` kwarg into a :class:`Retriever` instance.

    See the module docstring for the full mapping. URL-form specs
    require ``embedding_model`` because the backend needs it before any
    embedding is computed (collection / table creation runs on first
    use). Instance / subclass / ``None`` specs do not — the caller has
    already wired the embedding model into the instance.
    """
    if spec is None:
        return None
    if isinstance(spec, Retriever):
        return spec
    if isinstance(spec, type) and issubclass(spec, Retriever):
        return spec()
    if not isinstance(spec, str):
        raise RetrieverConfigError(
            f"Unsupported retriever spec {spec!r}. Expected URL string, Retriever "
            f"instance, Retriever subclass, or None."
        )
    url = spec
    if embedding_model is None:
        raise RetrieverConfigError(
            f"URL-form retriever spec {url!r} requires an ``embedding_model`` keyword argument."
        )
    if url.startswith("qdrant://"):
        # Lazy import keeps ``ajolopy.rag`` import-light when the
        # optional Qdrant extra is not installed (the constructor itself
        # surfaces the missing extra as RetrieverDependencyError).
        from .qdrant_retriever import QdrantRetriever

        return QdrantRetriever(url, embedding_model=embedding_model)
    if url.startswith("pgvector://"):
        from .pgvector_retriever import PgvectorRetriever

        return PgvectorRetriever(url, embedding_model=embedding_model)
    raise RetrieverConfigError(
        f"Unknown retriever URL scheme {url!r}. Supported: qdrant://, pgvector://."
    )


__all__ = ["resolve_retriever"]
