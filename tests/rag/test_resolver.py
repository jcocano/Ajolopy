"""Acceptance tests for :func:`resolve_retriever`."""

from collections.abc import Iterable
from typing import override

import pytest

from ajolopy.rag import (
    Document,
    PgvectorRetriever,
    QdrantRetriever,
    RetrievalHit,
    Retriever,
    resolve_retriever,
)
from ajolopy.rag.errors import RetrieverConfigError


class _NullRetriever(Retriever):
    @override
    async def index(self, documents: Iterable[Document]) -> None:
        return None

    @override
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
        return []

    @override
    async def clear(self) -> None:
        return None


def test_none_returns_none() -> None:
    assert resolve_retriever(None) is None


def test_instance_passes_through() -> None:
    instance = _NullRetriever()
    assert resolve_retriever(instance) is instance


def test_subclass_is_instantiated() -> None:
    resolved = resolve_retriever(_NullRetriever)
    assert isinstance(resolved, _NullRetriever)


def test_qdrant_url_resolves_to_qdrant_retriever() -> None:
    resolved = resolve_retriever(
        "qdrant://:memory:",
        embedding_model="text-embedding-3-small",
    )
    assert isinstance(resolved, QdrantRetriever)


def test_pgvector_url_resolves_to_pgvector_retriever() -> None:
    resolved = resolve_retriever(
        "pgvector://user:pass@localhost/db?table=ajolopy_rag_test",
        embedding_model="text-embedding-3-small",
    )
    assert isinstance(resolved, PgvectorRetriever)


def test_url_form_requires_embedding_model() -> None:
    with pytest.raises(RetrieverConfigError) as info:
        resolve_retriever("qdrant://:memory:")
    assert "embedding_model" in str(info.value)


def test_unknown_scheme_raises_config_error() -> None:
    with pytest.raises(RetrieverConfigError):
        resolve_retriever("ftp://nope", embedding_model="text-embedding-3-small")


def test_non_string_non_retriever_raises_config_error() -> None:
    with pytest.raises(RetrieverConfigError):
        resolve_retriever(42)


def test_all_documented_forms_resolve() -> None:
    """Smoke-test every documented URL form in a single test."""
    assert resolve_retriever(None) is None
    instance = _NullRetriever()
    assert resolve_retriever(instance) is instance
    assert isinstance(resolve_retriever(_NullRetriever), _NullRetriever)
    assert isinstance(
        resolve_retriever("qdrant://:memory:", embedding_model="text-embedding-3-small"),
        QdrantRetriever,
    )
    assert isinstance(
        resolve_retriever(
            "pgvector://user:pass@localhost/db",
            embedding_model="text-embedding-3-small",
        ),
        PgvectorRetriever,
    )
