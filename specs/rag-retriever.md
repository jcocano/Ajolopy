# AJ-62 — RAG retriever abstraction + Qdrant + pgvector backends

> Tracked in [`board.json`](../board.json) as `AJ-62`. Added during AJ-24's
> scoping conversation when the user clarified that vector-store work
> belongs to a separate abstraction.

## What

`Retriever` ABC for retrieval-augmented generation, plus two concrete
backends: `QdrantRetriever` and `PgvectorRetriever`. Distinct from
`Memory` (AJ-24) — `Memory` is chat-history; `Retriever` is semantic
document search. Embeddings come from the provider layer
(`provider.embed(texts)` from AJ-18 / AJ-20).

## Why

The wedge user wants their agent to ground answers in a document
corpus (RAG). Today they pick a vector DB + write client glue + roll
their own embeddings pipeline. `Retriever` collapses that into a
declarative ABC + 2 concrete backends.

## Public surface (v0.1)

```python
from ajolopy.rag import (
    Retriever, QdrantRetriever, PgvectorRetriever,
    Document, RetrievalHit, resolve_retriever,
    RetrieverError, RetrieverConfigError, RetrieverDependencyError,
    RetrieverRuntimeError,
)

@dataclass(slots=True, frozen=True)
class Document:
    id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(slots=True, frozen=True)
class RetrievalHit:
    document: Document
    score: float

class Retriever(abc.ABC):
    @abc.abstractmethod
    async def index(self, documents: Iterable[Document]) -> None: ...

    @abc.abstractmethod
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]: ...

    @abc.abstractmethod
    async def clear(self) -> None: ...

class QdrantRetriever(Retriever):
    def __init__(
        self,
        url: str,
        *,
        embedding_model: str,
        collection: str = "ajolopy-rag",
        embedding_dim: int | None = None,  # default from embedding_model registry
    ) -> None: ...

class PgvectorRetriever(Retriever):
    def __init__(
        self,
        url: str,
        *,
        embedding_model: str,
        table: str = "ajolopy_rag",
        embedding_dim: int | None = None,
    ) -> None: ...

def resolve_retriever(spec: object) -> Retriever | None: ...
```

### URL resolution

| URL                                  | Resolves to                                  |
|--------------------------------------|----------------------------------------------|
| `qdrant://host:6333/collection`      | `QdrantRetriever(url)`                        |
| `pgvector://user:pass@host/db?table=x` | `PgvectorRetriever(url)`                    |
| `Retriever` instance                  | Returns verbatim                              |
| `None`                                | Returns `None`                                |
| Anything else                         | `RetrieverConfigError`                        |

### Embeddings

Via the provider layer: the retriever calls
`provider.embed(texts) -> list[list[float]]`. `embedding_model` is
resolved through `resolve_provider(...)` same way `@Agent.model` is.

Initially supported models (from existing providers):
- `text-embedding-3-small` (OpenAI, 1536 dims)
- `text-embedding-3-large` (OpenAI, 3072 dims)
- `voyage-3` (via Anthropic-compatible if available, else error)

The retriever caches the provider instance lazily on first `index()` /
`query()` call.

### Backends

**`QdrantRetriever`** — lazy-imports `qdrant_client.AsyncQdrantClient`.
Behind `ajolopy[qdrant]` extra. Stores `(id, embedding, payload={text, metadata})`.
Collection created on first use with cosine distance + the
configured embedding dim.

**`PgvectorRetriever`** — lazy-imports `asyncpg`. Behind
`ajolopy[pgvector]` extra. Schema:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS <table> (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(<dim>) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_<table>_embedding ON <table>
    USING ivfflat (embedding vector_cosine_ops);
```
Created idempotently on first use.

### Errors

- `RetrieverError` (base), `RetrieverConfigError`,
  `RetrieverDependencyError`, `RetrieverRuntimeError`.

## Cross-cuts

- **`pyproject.toml`** — new extras:
  - `qdrant = ["qdrant-client>=1.10"]`
  - `pgvector = ["asyncpg>=0.30", "pgvector>=0.3"]`
- **`.github/workflows/ci.yml`** — add `--extra qdrant --extra pgvector`
  to pyright + pytest jobs (same pattern as `--extra mcp`).
- **No `@Agent` surface change in v0.1**. Users wire the retriever as
  a `@Tool` method themselves:
  ```python
  @Agent(...)
  class Worker:
      def __init__(self):
          self._kb = QdrantRetriever(...)

      @Tool
      async def search_kb(self, q: str) -> str:
          hits = await self._kb.query(q, k=3)
          return "\n".join(h.document.text for h in hits)
  ```
  An `@Agent(retriever=...)` kwarg can land in v0.2.

## Out of scope

- `@Agent(retriever=...)` kwarg → v0.2.
- Other vector backends (Weaviate, Pinecone, Chroma) → v0.2.
- Chunking strategies (recursive, semantic) → user's responsibility in
  v0.1; the retriever stores whatever `Document.text` it receives.
- Hybrid search (vector + keyword) → v0.2.
- Re-ranking → v0.2.

## Acceptance criteria

### `Retriever` ABC + dataclasses
- [x] `Document` and `RetrievalHit` are frozen + slotted dataclasses.
- [x] `Retriever` cannot be instantiated directly.
- [x] Subclass missing one method still abstract.

### `QdrantRetriever`
- [x] Roundtrip: `index([doc1, doc2])` → `query("q")` returns hits
      with scores. Verified against `fakeredis`-style mock — actually
      use Qdrant in-memory mode (`qdrant_client.QdrantClient(location=":memory:")`) for tests.
- [x] Missing `ajolopy[qdrant]` extra → `RetrieverDependencyError`
      at construction.
- [x] Collection created on first index call with correct dim.
- [x] `clear()` deletes the collection.
- [x] `k` parameter limits hits.
- [x] Multiple `index` calls accumulate (upsert).

### `PgvectorRetriever`
- [x] Roundtrip (gated on `AJOLOPY_TEST_PGVECTOR_URL` env var; skipped
      in CI; covered by class-instantiation + connection-error tests).
- [x] Missing `ajolopy[pgvector]` extra → `RetrieverDependencyError`.
- [x] Schema created idempotently.

### `resolve_retriever`
- [x] All URL schemes resolve correctly.
- [x] `None` → `None`.
- [x] Instance → verbatim.
- [x] Bad scheme → `RetrieverConfigError`.

### Public re-exports
- [x] `from ajolopy.rag import (...)` works.
- [x] `ajolopy.rag.__all__` matches.
- [x] No top-level re-exports.

## Implementation pointers

- New sub-package: `src/ajolopy/rag/`.
  - `__init__.py`, `base.py` (Retriever ABC + dataclasses),
    `errors.py`, `qdrant_retriever.py`, `pgvector_retriever.py`,
    `resolver.py`.
- `pyproject.toml`: 2 new extras.
- `.github/workflows/ci.yml`: extras in pyright + pytest jobs.
- Tests: `tests/rag/`.
- Reuse `resolve_provider` from `ajolopy.providers` for embedding
  model lookup.

## Implementation notes

- **Provider resolution.** Embedding-model strings route through the
  existing `resolve_provider` registry (`text-embedding-3-*` already
  resolves to the `openai` provider via the default routing table).
  `resolve_embedding_provider` (in `src/ajolopy/rag/_embeddings.py`)
  wraps the registry lookup + instantiation so retriever callers see
  uniform `RetrieverConfigError` / `RetrieverRuntimeError` instead of
  registry-specific exception types. The provider is cached on the
  retriever instance and resolved lazily on first `index` / `query`
  so test fakes can register *after* construction.

- **Embedding-dim defaults.** Hard-coded for the three v0.1 OpenAI
  embedding models (`text-embedding-3-small=1536`,
  `text-embedding-3-large=3072`, `text-embedding-ada-002=1536`). Any
  other model forces the caller to pass `embedding_dim=<int>`
  explicitly — fail-fast at construction time, since collection /
  table creation needs the dim before the first embedding round-trip.

- **Qdrant point ids.** Qdrant only accepts UUID or unsigned-int point
  ids; the caller's `Document.id` is mapped through `uuid.uuid5` with a
  module-level namespace UUID so the mapping stays deterministic across
  processes. The original `Document.id` is preserved verbatim inside the
  point's payload (`payload["doc_id"]`) and returned on every hit.

- **Qdrant URL grammar.** `qdrant://host:port` → `AsyncQdrantClient(host, port)`;
  `:memory:` / `qdrant://:memory:` → in-process `location=":memory:"`
  mode; raw `http(s)://` URLs pass through unchanged. Tests use the
  in-process mode so no Qdrant container is required.

- **pgvector URL grammar.** `pgvector://...?table=<name>` is rewritten
  to `postgresql://...` (without the `table=` query string) before
  asyncpg sees it; the `?table=` value overrides the constructor's
  `table=` kwarg so the resolver can encode the destination table in a
  single URL.

- **pgvector schema lifecycle.** `CREATE EXTENSION IF NOT EXISTS vector`
  + `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` run
  idempotently behind an asyncio lock on first use. The vector codec is
  registered per pooled connection through asyncpg's `init=` callback so
  every borrowed connection encodes / decodes `vector(N)` natively.
  Cosine similarity is computed as `1 - (embedding <=> $1)` so the
  hit score has "higher is more similar" semantics consistent with
  `QdrantRetriever`.

- **Resolver scope.** `resolve_retriever` accepts `None` / instance /
  subclass / `qdrant://` / `pgvector://`. The signature already takes
  an `embedding_model` kwarg so wiring `@Agent(retriever=...)` in v0.2
  is a no-op on the resolver side.

- **Public surface re-exports.** Only the 10 names in
  `ajolopy.rag.__all__` (`Document`, `PgvectorRetriever`,
  `QdrantRetriever`, `RetrievalHit`, `Retriever`,
  `RetrieverConfigError`, `RetrieverDependencyError`,
  `RetrieverError`, `RetrieverRuntimeError`, `resolve_retriever`).
  Nothing leaks into `ajolopy` directly — RAG stays a sub-package in
  v0.1, mirroring `ajolopy.memory`.
