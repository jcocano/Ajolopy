"""Acceptance tests for :class:`QdrantRetriever`.

The Qdrant SDK ships an in-process mode
(``QdrantClient(location=":memory:")``); :class:`QdrantRetriever`
routes the ``:memory:`` / ``qdrant://:memory:`` literals there so the
suite never depends on a running Qdrant container.

Tests exercise the full contract: dependency error, collection
lifecycle, upsert + query roundtrip, ``k`` capping, multi-call
accumulation, and ``clear()`` deleting the collection.
"""

from typing import Any

import pytest

from ajolopy.rag import Document, QdrantRetriever
from ajolopy.rag.errors import RetrieverConfigError, RetrieverDependencyError


def test_missing_extra_raises_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate missing ``qdrant-client`` extra by sabotaging the import path."""
    import builtins

    real_import = builtins.__import__

    def _patched_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "qdrant_client" or (name.startswith("qdrant_client") and not level):
            raise ImportError("qdrant-client is not installed (simulated)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    with pytest.raises(RetrieverDependencyError) as info:
        QdrantRetriever(":memory:", embedding_model="text-embedding-3-small")
    assert "ajolopy[qdrant]" in str(info.value)


def test_unknown_model_without_explicit_dim_raises_config_error() -> None:
    with pytest.raises(RetrieverConfigError):
        QdrantRetriever(":memory:", embedding_model="some-unknown-model")


def test_known_model_uses_default_dim() -> None:
    retriever = QdrantRetriever(":memory:", embedding_model="text-embedding-3-small")
    assert retriever._embedding_dim == 1536


def test_known_large_model_uses_default_dim() -> None:
    retriever = QdrantRetriever(":memory:", embedding_model="text-embedding-3-large")
    assert retriever._embedding_dim == 3072


def test_explicit_dim_overrides_default() -> None:
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        embedding_dim=8,
    )
    assert retriever._embedding_dim == 8


def test_zero_dim_rejected() -> None:
    with pytest.raises(RetrieverConfigError):
        QdrantRetriever(
            ":memory:",
            embedding_model="text-embedding-3-small",
            embedding_dim=0,
        )


def test_empty_collection_name_rejected() -> None:
    with pytest.raises(RetrieverConfigError):
        QdrantRetriever(
            ":memory:",
            embedding_model="text-embedding-3-small",
            collection="",
        )


@pytest.mark.asyncio
async def test_index_query_roundtrip(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_roundtrip",
    )
    await retriever.index(
        [
            Document(id="doc-1", text="alpha bravo", metadata={"topic": "greek"}),
            Document(id="doc-2", text="charlie delta", metadata={"topic": "greek"}),
            Document(id="doc-3", text="echo foxtrot", metadata={"topic": "phonetic"}),
        ]
    )
    hits = await retriever.query("alpha bravo", k=3)
    assert hits, "query returned no hits"
    assert hits[0].document.id == "doc-1"
    assert hits[0].document.text == "alpha bravo"
    assert hits[0].document.metadata == {"topic": "greek"}
    assert hits[0].score == pytest.approx(1.0, rel=1e-3)


@pytest.mark.asyncio
async def test_k_limits_hits(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_k",
    )
    await retriever.index([Document(id=f"doc-{i}", text=f"text-{i}") for i in range(10)])
    hits = await retriever.query("text-3", k=2)
    assert len(hits) == 2


@pytest.mark.asyncio
async def test_query_with_zero_k_returns_empty(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_zero_k",
    )
    await retriever.index([Document(id="doc-1", text="alpha")])
    assert await retriever.query("alpha", k=0) == []


@pytest.mark.asyncio
async def test_multiple_index_calls_accumulate(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_accumulate",
    )
    await retriever.index([Document(id="doc-1", text="alpha")])
    await retriever.index([Document(id="doc-2", text="beta")])
    hits_a = await retriever.query("alpha", k=5)
    hits_b = await retriever.query("beta", k=5)
    ids_a = [h.document.id for h in hits_a]
    ids_b = [h.document.id for h in hits_b]
    assert "doc-1" in ids_a
    assert "doc-2" in ids_b


@pytest.mark.asyncio
async def test_upsert_overwrites_same_id(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_upsert",
    )
    await retriever.index([Document(id="doc-1", text="alpha", metadata={"v": 1})])
    await retriever.index([Document(id="doc-1", text="alpha-updated", metadata={"v": 2})])
    hits = await retriever.query("alpha-updated", k=1)
    assert hits[0].document.id == "doc-1"
    assert hits[0].document.text == "alpha-updated"
    assert hits[0].document.metadata == {"v": 2}


@pytest.mark.asyncio
async def test_collection_created_with_configured_dim(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_dim",
    )
    await retriever.index([Document(id="doc-1", text="alpha")])
    info: Any = await retriever._client.get_collection("ajolopy_rag_test_dim")
    # ``params.vectors.size`` carries the configured dim — drill in
    # leniently because the SDK returns rich pydantic models.
    vectors_config: Any = info.config.params.vectors
    size: Any = getattr(vectors_config, "size", None)
    if size is None:
        size = vectors_config["size"]
    assert int(size) == retriever._embedding_dim


@pytest.mark.asyncio
async def test_clear_deletes_the_collection(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_clear",
    )
    await retriever.index([Document(id="doc-1", text="alpha")])
    assert await retriever._client.collection_exists("ajolopy_rag_test_clear")
    await retriever.clear()
    assert not await retriever._client.collection_exists("ajolopy_rag_test_clear")


@pytest.mark.asyncio
async def test_empty_index_is_a_noop(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    retriever = QdrantRetriever(
        ":memory:",
        embedding_model="text-embedding-3-small",
        collection="ajolopy_rag_test_empty",
    )
    # No call to ``embed`` is expected when the batch is empty — the
    # retriever should short-circuit. Successful return is the contract.
    await retriever.index([])
