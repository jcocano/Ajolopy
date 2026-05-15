"""Acceptance tests for :class:`PgvectorRetriever`.

There is no mature in-process pgvector fake (the SDK speaks the
PostgreSQL wire protocol end-to-end), so the deterministic coverage
here focuses on:

- Constructor validation (table-name regex, URL rewrite, missing extra,
  unknown-model + missing-dim).
- Connection-error surface (an unreachable URL raises
  :class:`RetrieverRuntimeError` on first use).
- A real-Postgres round-trip guarded behind
  ``AJOLOPY_TEST_PGVECTOR_URL`` — CI does not set this env var; local
  maintainers set it to verify end-to-end behaviour against a real
  database with the pgvector extension installed.
"""

import os
from typing import Any

import pytest

from ajolopy.rag import Document, PgvectorRetriever
from ajolopy.rag.errors import (
    RetrieverConfigError,
    RetrieverDependencyError,
    RetrieverRuntimeError,
)
from ajolopy.rag.pgvector_retriever import _rewrite_pgvector_url

_PGVECTOR_URL = os.getenv("AJOLOPY_TEST_PGVECTOR_URL")
_REQUIRES_REAL_PGVECTOR = pytest.mark.skipif(
    _PGVECTOR_URL is None,
    reason="Set AJOLOPY_TEST_PGVECTOR_URL to run PgvectorRetriever integration tests.",
)


def test_default_table_constructor_succeeds() -> None:
    retriever = PgvectorRetriever(
        "postgresql://user:pass@localhost/db",
        embedding_model="text-embedding-3-small",
    )
    assert retriever._table == "ajolopy_rag"


def test_custom_table_kwarg_is_accepted() -> None:
    retriever = PgvectorRetriever(
        "postgresql://user:pass@localhost/db",
        embedding_model="text-embedding-3-small",
        table="custom_table",
    )
    assert retriever._table == "custom_table"


def test_url_query_param_overrides_table_kwarg() -> None:
    retriever = PgvectorRetriever(
        "pgvector://user:pass@localhost/db?table=from_url",
        embedding_model="text-embedding-3-small",
        table="from_kwarg",
    )
    assert retriever._table == "from_url"


def test_pgvector_url_is_rewritten_to_postgresql() -> None:
    rewritten, table = _rewrite_pgvector_url("pgvector://user:pass@localhost/db?table=demo")
    assert rewritten.startswith("postgresql://")
    assert table == "demo"
    assert "table=" not in rewritten


def test_invalid_table_name_raises_config_error() -> None:
    with pytest.raises(RetrieverConfigError):
        PgvectorRetriever(
            "postgresql://user:pass@localhost/db",
            embedding_model="text-embedding-3-small",
            table="evil; DROP TABLE users; --",
        )


def test_unknown_model_without_explicit_dim_raises_config_error() -> None:
    with pytest.raises(RetrieverConfigError):
        PgvectorRetriever(
            "postgresql://user:pass@localhost/db",
            embedding_model="some-unknown-model",
        )


def test_zero_dim_rejected() -> None:
    with pytest.raises(RetrieverConfigError):
        PgvectorRetriever(
            "postgresql://user:pass@localhost/db",
            embedding_model="text-embedding-3-small",
            embedding_dim=0,
        )


def test_known_model_uses_default_dim() -> None:
    retriever = PgvectorRetriever(
        "postgresql://user:pass@localhost/db",
        embedding_model="text-embedding-3-small",
    )
    assert retriever._embedding_dim == 1536


def test_missing_extra_raises_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate missing ``asyncpg`` extra by sabotaging the import path."""
    import builtins

    real_import = builtins.__import__

    def _patched_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "asyncpg" or name.startswith("pgvector"):
            raise ImportError(f"{name} is not installed (simulated)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    with pytest.raises(RetrieverDependencyError) as info:
        PgvectorRetriever(
            "postgresql://user:pass@localhost/db",
            embedding_model="text-embedding-3-small",
        )
    assert "ajolopy[pgvector]" in str(info.value)


@pytest.mark.asyncio
async def test_unreachable_url_raises_runtime_error(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    # 127.0.0.1:1 is reserved as an invalid endpoint; asyncpg surfaces a
    # connection refused / OS error. ``PgvectorRetriever`` wraps it as
    # :class:`RetrieverRuntimeError` so callers can catch on a single type.
    retriever = PgvectorRetriever(
        "postgresql://user:pass@127.0.0.1:1/postgres",
        embedding_model="text-embedding-3-small",
    )
    with pytest.raises(RetrieverRuntimeError):
        await retriever.query("anything", k=1)


@_REQUIRES_REAL_PGVECTOR
@pytest.mark.asyncio
async def test_round_trip_against_real_pgvector(fake_embedding_provider: type) -> None:
    _ = fake_embedding_provider
    assert _PGVECTOR_URL is not None
    retriever = PgvectorRetriever(
        _PGVECTOR_URL,
        embedding_model="text-embedding-3-small",
        table="ajolopy_rag_test_roundtrip",
    )
    await retriever.clear()
    await retriever.index(
        [
            Document(id="doc-1", text="alpha bravo", metadata={"topic": "greek"}),
            Document(id="doc-2", text="charlie delta", metadata={"topic": "greek"}),
        ]
    )
    hits = await retriever.query("alpha bravo", k=2)
    assert hits
    assert hits[0].document.id == "doc-1"
    await retriever.clear()


@_REQUIRES_REAL_PGVECTOR
@pytest.mark.asyncio
async def test_schema_idempotent_on_second_construction(
    fake_embedding_provider: type,
) -> None:
    _ = fake_embedding_provider
    assert _PGVECTOR_URL is not None
    first = PgvectorRetriever(
        _PGVECTOR_URL,
        embedding_model="text-embedding-3-small",
        table="ajolopy_rag_test_idem",
    )
    await first.index([Document(id="doc-1", text="alpha")])
    second = PgvectorRetriever(
        _PGVECTOR_URL,
        embedding_model="text-embedding-3-small",
        table="ajolopy_rag_test_idem",
    )
    # Re-running the schema init on a fresh instance must not raise.
    await second.index([Document(id="doc-2", text="beta")])
    await second.clear()
