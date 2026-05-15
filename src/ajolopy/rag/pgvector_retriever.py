"""PostgreSQL + pgvector-backed :class:`Retriever` implementation.

Uses ``asyncpg`` for the connection pool (created lazily on first
operation so the constructor stays sync) and the ``pgvector`` Python
package for the type adapter that turns Python ``list[float]`` into
``vector(N)`` values. The schema:

.. code-block:: sql

    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS <table> (
        id TEXT PRIMARY KEY,
        text TEXT NOT NULL,
        metadata JSONB DEFAULT '{}',
        embedding vector(<dim>) NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_<table>_embedding ON <table>
        USING ivfflat (embedding vector_cosine_ops);

is created idempotently on first use so the backend is safe against
repeated process starts and concurrent writers.

Both ``asyncpg`` and ``pgvector`` are imported lazily inside
``__init__``; a missing extra surfaces immediately as
:class:`RetrieverDependencyError` with a ``pip install`` hint.

The ``url`` accepts the framework's ``pgvector://...`` shorthand (the
scheme is rewritten to ``postgresql://``) and the ``?table=`` query
parameter so the resolver can encode the destination table in a single
URL string.
"""

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any, override
from urllib.parse import parse_qs, urlsplit, urlunsplit

from ._embeddings import default_embedding_dim, resolve_embedding_provider
from .base import Document, RetrievalHit, Retriever
from .errors import (
    RetrieverConfigError,
    RetrieverDependencyError,
    RetrieverRuntimeError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ajolopy.providers import LLMProvider


_DEPENDENCY_HINT = (
    "The optional `asyncpg` + `pgvector` SDKs are not installed. Install "
    "them with `pip install ajolopy[pgvector]` (or "
    "`uv add 'ajolopy[pgvector]'`) to use PgvectorRetriever."
)

# Match the conservative regex used by PostgresMemory so callers can
# pass ``schema.table`` qualifiers without smuggling SQL fragments
# through the ``table=`` kwarg.
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _rewrite_pgvector_url(url: str) -> tuple[str, str | None]:
    """Strip the ``pgvector://`` scheme and extract ``?table=``.

    Returns the ``postgresql://`` URL asyncpg consumes plus the optional
    ``table`` override (or ``None`` when the URL did not carry one).
    """
    if not url.startswith("pgvector://"):
        return url, None
    parsed = urlsplit(url)
    table_override: str | None = None
    remaining_qs: list[tuple[str, str]] = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key == "table" and values:
            table_override = values[0]
        else:
            for value in values:
                remaining_qs.append((key, value))
    new_query = "&".join(f"{k}={v}" for k, v in remaining_qs)
    rewritten = urlunsplit(("postgresql", parsed.netloc, parsed.path, new_query, ""))
    return rewritten, table_override


class PgvectorRetriever(Retriever):
    """PostgreSQL + pgvector-backed semantic retriever.

    ``url`` accepts the framework's
    ``pgvector://user:pass@host/db?table=...`` shorthand and the raw
    ``postgresql://...`` form asyncpg parses natively. ``table`` defaults
    to ``ajolopy_rag``; a ``?table=`` query parameter on the URL
    overrides the kwarg so the resolver can encode the table without an
    extra config call.
    """

    def __init__(
        self,
        url: str,
        *,
        embedding_model: str,
        table: str = "ajolopy_rag",
        embedding_dim: int | None = None,
    ) -> None:
        rewritten_url, table_override = _rewrite_pgvector_url(url)
        effective_table = table_override or table
        if not _TABLE_NAME_RE.fullmatch(effective_table):
            raise RetrieverConfigError(
                f"Invalid pgvector table name {effective_table!r}: must match "
                f"{_TABLE_NAME_RE.pattern}."
            )
        try:
            import asyncpg
            import pgvector.asyncpg as _pgvector_asyncpg
        except ImportError as exc:
            raise RetrieverDependencyError(_DEPENDENCY_HINT) from exc
        # ``pgvector.asyncpg.register_vector`` is partially typed in the
        # upstream package; rebind through ``Any`` so callers can build
        # the asyncpg pool ``init`` callback without leaking the
        # incomplete annotation into our public surface.
        _pgvector_asyncpg_any: Any = _pgvector_asyncpg
        register_vector: Any = _pgvector_asyncpg_any.register_vector
        if embedding_dim is None:
            embedding_dim = default_embedding_dim(embedding_model)
        if embedding_dim is None:
            raise RetrieverConfigError(
                f"Unable to infer embedding dimension for {embedding_model!r}. "
                f"Pass ``embedding_dim=<int>`` explicitly."
            )
        if embedding_dim <= 0:
            raise RetrieverConfigError(
                f"embedding_dim must be a positive integer, got {embedding_dim!r}."
            )
        self._url = rewritten_url
        self._table = effective_table
        self._embedding_model = embedding_model
        self._embedding_dim = embedding_dim
        self._asyncpg: Any = asyncpg
        self._register_vector: Any = register_vector
        self._pool: Any = None
        self._provider: LLMProvider | None = None
        self._schema_ready = False
        self._init_lock = asyncio.Lock()

    @property
    def _index_name(self) -> str:
        return f"idx_{self._table.replace('.', '_')}_embedding"

    def _ensure_provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = resolve_embedding_provider(self._embedding_model)
        return self._provider

    async def _init_connection(self, conn: Any) -> None:
        # ``register_vector`` teaches asyncpg how to encode/decode the
        # ``vector`` type. Must run on every connection acquired from
        # the pool — pooled connections retain their own codec state.
        await self._register_vector(conn)

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            try:
                self._pool = await self._asyncpg.create_pool(
                    self._url,
                    init=self._init_connection,
                )
            except Exception as exc:
                raise RetrieverRuntimeError(
                    f"PgvectorRetriever could not connect to {self._url!r}: {exc}"
                ) from exc
        return self._pool

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._init_lock:
            if self._schema_ready:
                return
            pool = await self._ensure_pool()
            # ``self._table`` is regex-validated in ``__init__`` so the
            # f-string cannot smuggle a SQL fragment; ``embedding_dim``
            # is an int validated against the positive-integer
            # invariant.
            extension_sql = "CREATE EXTENSION IF NOT EXISTS vector"
            create_sql = (
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "id TEXT PRIMARY KEY, "
                "text TEXT NOT NULL, "
                "metadata JSONB DEFAULT '{}', "
                f"embedding vector({self._embedding_dim}) NOT NULL)"
            )
            index_sql = (
                f"CREATE INDEX IF NOT EXISTS {self._index_name} ON {self._table} "
                "USING ivfflat (embedding vector_cosine_ops)"
            )
            try:
                async with pool.acquire() as conn:
                    await conn.execute(extension_sql)
                    await conn.execute(create_sql)
                    await conn.execute(index_sql)
            except Exception as exc:
                raise RetrieverRuntimeError(f"PgvectorRetriever schema init failed: {exc}") from exc
            self._schema_ready = True

    async def _embed_one(self, text: str) -> list[float]:
        provider = self._ensure_provider()
        try:
            vectors = await provider.embed(model=self._embedding_model, text=text)
        except Exception as exc:
            raise RetrieverRuntimeError(
                f"PgvectorRetriever embedding failed for model {self._embedding_model!r}: {exc}"
            ) from exc
        if not vectors:
            raise RetrieverRuntimeError(
                "Embedding provider returned no vectors for a single-text request."
            )
        return list(vectors[0])

    async def _embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        provider = self._ensure_provider()
        try:
            vectors = await provider.embed(model=self._embedding_model, text=texts)
        except Exception as exc:
            raise RetrieverRuntimeError(
                f"PgvectorRetriever embedding failed for model {self._embedding_model!r}: {exc}"
            ) from exc
        if len(vectors) != len(texts):
            raise RetrieverRuntimeError(
                f"Embedding provider returned {len(vectors)} vectors for {len(texts)} inputs."
            )
        return [list(v) for v in vectors]

    @override
    async def index(self, documents: Iterable[Document]) -> None:
        docs = list(documents)
        if not docs:
            return
        await self._ensure_schema()
        vectors = await self._embed_many([d.text for d in docs])
        for vec in vectors:
            if len(vec) != self._embedding_dim:
                raise RetrieverRuntimeError(
                    f"Embedding dimension mismatch: provider returned "
                    f"{len(vec)} but table was created with "
                    f"{self._embedding_dim}."
                )
        # Table name is regex-validated at construction.
        sql = (
            f"INSERT INTO {self._table}(id, text, metadata, embedding) "  # noqa: S608
            "VALUES ($1, $2, $3::jsonb, $4) "
            "ON CONFLICT (id) DO UPDATE SET "
            "text = EXCLUDED.text, "
            "metadata = EXCLUDED.metadata, "
            "embedding = EXCLUDED.embedding"
        )
        pool = await self._ensure_pool()
        try:
            async with pool.acquire() as conn:
                for doc, vec in zip(docs, vectors, strict=True):
                    await conn.execute(
                        sql,
                        doc.id,
                        doc.text,
                        json.dumps(dict(doc.metadata)),
                        vec,
                    )
        except Exception as exc:
            raise RetrieverRuntimeError(f"PgvectorRetriever.index upsert failed: {exc}") from exc

    @override
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
        if k <= 0:
            return []
        await self._ensure_schema()
        vector = await self._embed_one(text)
        # Cosine distance in pgvector is the ``<=>`` operator; similarity
        # is ``1 - distance`` so callers see a "higher is more similar"
        # score consistent with QdrantRetriever.
        sql = (
            f"SELECT id, text, metadata::text AS metadata_json, "  # noqa: S608
            f"1 - (embedding <=> $1) AS similarity "
            f"FROM {self._table} ORDER BY embedding <=> $1 LIMIT $2"
        )
        pool = await self._ensure_pool()
        try:
            async with pool.acquire() as conn:
                rows: Any = await conn.fetch(sql, vector, k)
        except Exception as exc:
            raise RetrieverRuntimeError(f"PgvectorRetriever.query failed: {exc}") from exc
        hits: list[RetrievalHit] = []
        for row in rows:
            metadata_raw: Any = row["metadata_json"]
            metadata: dict[str, Any]
            if isinstance(metadata_raw, str) and metadata_raw:
                try:
                    parsed_any: Any = json.loads(metadata_raw)
                except json.JSONDecodeError:
                    parsed_any = {}
                if isinstance(parsed_any, dict):
                    metadata = {str(k): v for k, v in parsed_any.items()}  # type: ignore[reportUnknownVariableType]
                else:
                    metadata = {}
            else:
                metadata = {}
            document = Document(
                id=str(row["id"]),
                text=str(row["text"]),
                metadata=metadata,
            )
            hits.append(RetrievalHit(document=document, score=float(row["similarity"])))
        return hits

    @override
    async def clear(self) -> None:
        await self._ensure_schema()
        # Table name is regex-validated at construction.
        sql = f"TRUNCATE TABLE {self._table}"
        pool = await self._ensure_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(sql)
        except Exception as exc:
            raise RetrieverRuntimeError(f"PgvectorRetriever.clear failed: {exc}") from exc


__all__ = ["PgvectorRetriever"]
