"""Qdrant-backed :class:`Retriever` implementation.

Uses ``qdrant_client.AsyncQdrantClient`` for production HTTP / gRPC and
``qdrant_client.QdrantClient(location=":memory:")`` for tests (wrapped
through :class:`AsyncQdrantClient` with ``location=":memory:"`` so the
async surface stays uniform).

The SDK is imported lazily inside ``__init__`` so importing
:mod:`ajolopy.rag` does not require ``ajolopy[qdrant]`` to be installed.
A missing extra surfaces immediately as
:class:`RetrieverDependencyError` with a ``pip install`` hint.

Collection layout:

- Vectors: dense, ``size=embedding_dim``, cosine distance.
- Point id: UUID5 of the caller's ``Document.id`` so Qdrant accepts the
  identifier while ``Document.id`` (which may be any string) is
  preserved verbatim inside the payload.
- Payload: ``{"doc_id": <str>, "text": <str>, "metadata": <dict>}``.
"""

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, override

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
    "The optional `qdrant-client` SDK is not installed. Install it with "
    "`pip install ajolopy[qdrant]` (or `uv add 'ajolopy[qdrant]'`) "
    "to use QdrantRetriever."
)

# Namespace UUID for deriving deterministic point ids from caller-supplied
# string ``Document.id`` values. Generated once via ``uuid.uuid4()`` and
# pinned so the mapping stays stable across processes and library
# versions.
_QDRANT_ID_NAMESPACE = uuid.UUID("c8b2c1cc-7d8c-4e9e-9a8f-2c1f6bdb3b3a")


def _point_id_for(doc_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_ID_NAMESPACE, doc_id))


class QdrantRetriever(Retriever):
    """Qdrant-backed semantic retriever.

    ``url`` accepts the framework's ``qdrant://host:port/collection``
    shorthand as well as raw ``http://`` / ``https://`` URLs that the
    Qdrant SDK consumes natively. The ``:memory:`` literal routes to
    Qdrant's in-process mode (zero-dependency, used by the test suite).

    The provider for ``embedding_model`` is resolved through
    :func:`ajolopy.providers.resolve_provider` so the retriever stays
    provider-agnostic. The provider is instantiated lazily on first
    ``index`` / ``query`` so unit-test fakes can be wired by the time
    the first embedding is computed.
    """

    def __init__(
        self,
        url: str,
        *,
        embedding_model: str,
        collection: str = "ajolopy-rag",
        embedding_dim: int | None = None,
    ) -> None:
        try:
            import qdrant_client
            from qdrant_client import models as qdrant_models
        except ImportError as exc:
            raise RetrieverDependencyError(_DEPENDENCY_HINT) from exc
        if not collection:
            raise RetrieverConfigError("QdrantRetriever requires a non-empty collection name.")
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
        self._url = url
        self._collection = collection
        self._embedding_model = embedding_model
        self._embedding_dim = embedding_dim
        self._qdrant: Any = qdrant_client
        self._models: Any = qdrant_models
        self._client: Any = self._build_client(qdrant_client, url)
        self._provider: LLMProvider | None = None
        self._collection_ready = False
        self._init_lock = asyncio.Lock()

    @staticmethod
    def _build_client(qdrant_client: Any, url: str) -> Any:
        # ``:memory:`` and ``qdrant://:memory:`` route to in-process mode
        # so unit tests never need a running Qdrant container.
        if url in {":memory:", "qdrant://:memory:"}:
            return qdrant_client.AsyncQdrantClient(location=":memory:")
        if url.startswith("qdrant://"):
            # ``qdrant://host:port`` → strip the scheme and feed
            # ``host=`` / ``port=`` so the SDK builds the right HTTP URL.
            rest = url.removeprefix("qdrant://")
            host_port, _, _ = rest.partition("/")
            host, _, port_str = host_port.partition(":")
            port = int(port_str) if port_str else 6333
            return qdrant_client.AsyncQdrantClient(host=host or "localhost", port=port)
        # Pass-through for ``http://`` / ``https://`` URLs.
        return qdrant_client.AsyncQdrantClient(url=url)

    def _ensure_provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = resolve_embedding_provider(self._embedding_model)
        return self._provider

    async def _embed_one(self, text: str) -> list[float]:
        provider = self._ensure_provider()
        try:
            vectors = await provider.embed(model=self._embedding_model, text=text)
        except Exception as exc:
            raise RetrieverRuntimeError(
                f"QdrantRetriever embedding failed for model {self._embedding_model!r}: {exc}"
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
                f"QdrantRetriever embedding failed for model {self._embedding_model!r}: {exc}"
            ) from exc
        if len(vectors) != len(texts):
            raise RetrieverRuntimeError(
                f"Embedding provider returned {len(vectors)} vectors for {len(texts)} inputs."
            )
        return [list(v) for v in vectors]

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        async with self._init_lock:
            if self._collection_ready:
                return
            try:
                exists = await self._client.collection_exists(self._collection)
            except Exception as exc:
                raise RetrieverRuntimeError(
                    f"QdrantRetriever could not check collection existence: {exc}"
                ) from exc
            if not exists:
                try:
                    await self._client.create_collection(
                        collection_name=self._collection,
                        vectors_config=self._models.VectorParams(
                            size=self._embedding_dim,
                            distance=self._models.Distance.COSINE,
                        ),
                    )
                except Exception as exc:
                    raise RetrieverRuntimeError(
                        f"QdrantRetriever could not create collection {self._collection!r}: {exc}"
                    ) from exc
            self._collection_ready = True

    @override
    async def index(self, documents: Iterable[Document]) -> None:
        docs = list(documents)
        if not docs:
            return
        await self._ensure_collection()
        vectors = await self._embed_many([d.text for d in docs])
        for vec in vectors:
            if len(vec) != self._embedding_dim:
                raise RetrieverRuntimeError(
                    f"Embedding dimension mismatch: provider returned "
                    f"{len(vec)} but collection was created with "
                    f"{self._embedding_dim}."
                )
        points = [
            self._models.PointStruct(
                id=_point_id_for(doc.id),
                vector=vec,
                payload={
                    "doc_id": doc.id,
                    "text": doc.text,
                    "metadata": dict(doc.metadata),
                },
            )
            for doc, vec in zip(docs, vectors, strict=True)
        ]
        try:
            await self._client.upsert(
                collection_name=self._collection,
                points=points,
            )
        except Exception as exc:
            raise RetrieverRuntimeError(f"QdrantRetriever.index upsert failed: {exc}") from exc

    @override
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
        if k <= 0:
            return []
        await self._ensure_collection()
        vector = await self._embed_one(text)
        try:
            result: Any = await self._client.query_points(
                collection_name=self._collection,
                query=vector,
                limit=k,
                with_payload=True,
            )
        except Exception as exc:
            raise RetrieverRuntimeError(f"QdrantRetriever.query failed: {exc}") from exc
        points: Any = getattr(result, "points", None) or []
        hits: list[RetrievalHit] = []
        for point in points:
            payload_raw: Any = getattr(point, "payload", None) or {}
            payload: dict[str, Any] = (
                {str(k): v for k, v in payload_raw.items()}  # type: ignore[reportUnknownVariableType]
                if isinstance(payload_raw, dict)
                else {}
            )
            doc_id_any: Any = payload.get("doc_id")
            text_any: Any = payload.get("text")
            metadata_any: Any = payload.get("metadata")
            metadata: dict[str, Any] = (
                {str(k): v for k, v in metadata_any.items()}  # type: ignore[reportUnknownVariableType]
                if isinstance(metadata_any, dict)
                else {}
            )
            document = Document(
                id=str(doc_id_any) if doc_id_any is not None else "",
                text=str(text_any) if text_any is not None else "",
                metadata=metadata,
            )
            score_any: Any = getattr(point, "score", 0.0)
            hits.append(RetrievalHit(document=document, score=float(score_any)))
        return hits

    @override
    async def clear(self) -> None:
        try:
            await self._client.delete_collection(collection_name=self._collection)
        except Exception as exc:
            raise RetrieverRuntimeError(f"QdrantRetriever.clear failed: {exc}") from exc
        self._collection_ready = False


__all__ = ["QdrantRetriever"]
