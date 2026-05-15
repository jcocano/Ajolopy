"""Public surface contract for :mod:`ajolopy.rag`.

The spec promises a fixed re-export list and zero top-level
re-exports. These tests pin both invariants so accidental additions or
top-level leaks are caught at CI time.
"""

import ajolopy
import ajolopy.rag as rag


def test_all_exported_names_match_spec() -> None:
    expected = {
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
    }
    assert set(rag.__all__) == expected


def test_every_name_in_all_is_importable() -> None:
    for name in rag.__all__:
        assert hasattr(rag, name), f"Missing re-export: {name}"


def test_no_top_level_re_exports() -> None:
    # The RAG primitives stay namespaced under ``ajolopy.rag`` in v0.1;
    # they must not leak into ``ajolopy`` directly.
    for name in (
        "Retriever",
        "Document",
        "RetrievalHit",
        "QdrantRetriever",
        "PgvectorRetriever",
        "resolve_retriever",
    ):
        assert not hasattr(ajolopy, name), f"Unexpected top-level re-export: {name}"
