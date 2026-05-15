"""``Retriever`` ABC and the immutable value types consumed by it.

The contract is deliberately narrow: index a batch of documents, query
the corpus for the top ``k`` semantically nearest hits, and wipe the
backing store. Richer surfaces (filters, hybrid search, MMR re-ranking)
land post-v0.1 as additive methods or kwargs that default to no-ops.

``Document`` and :class:`RetrievalHit` are frozen + slotted dataclasses so
they are cheap to construct, immutable by default, and play well with
``dict``-keyed caches when callers reuse a corpus snapshot across
queries.

All methods are coroutines because production backends are I/O-bound;
forcing every call site to ``await`` keeps the framework free of a
sync/async split.
"""

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class Document:
    """A single indexable record.

    ``id`` is the caller's stable identifier (used for upserts).
    ``text`` is the raw content that gets embedded. ``metadata`` is an
    arbitrary mapping persisted alongside the embedding and returned on
    every hit; the retriever does not interpret it.
    """

    id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=lambda: dict[str, Any]())


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """A single retrieval result.

    ``score`` is the similarity score reported by the backend (cosine
    similarity for both v0.1 backends; higher is more similar). Callers
    that want a distance instead can compute ``1.0 - score``.
    """

    document: Document
    score: float


class Retriever(abc.ABC):
    """Semantic-document retrieval contract.

    Distinct from :class:`ajolopy.memory.Memory` — :class:`Memory` is
    chat-history persistence keyed by ``session_id``; :class:`Retriever`
    is a semantic document index keyed by ``Document.id``.
    """

    @abc.abstractmethod
    async def index(self, documents: Iterable[Document]) -> None:
        """Index ``documents`` (upsert semantics on ``Document.id``)."""

    @abc.abstractmethod
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
        """Return the top ``k`` hits ordered from most to least similar."""

    @abc.abstractmethod
    async def clear(self) -> None:
        """Remove every indexed document from the backing store."""


__all__ = ["Document", "RetrievalHit", "Retriever"]
