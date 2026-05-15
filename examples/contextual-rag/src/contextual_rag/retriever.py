"""Contextual + hybrid ``Retriever`` over a JSONL chunk index.

Subclasses :class:`ajolopy.rag.Retriever` (the AJ-62 escape hatch) the
same way ``dogfood/docsbot`` does, but with three substantive upgrades:

- **Contextual chunking.** Every chunk loaded from ``data/index.jsonl``
  carries a ``context_summary`` and a ``section`` heading sourced by the
  index builder. The retriever does not invent the summary at query
  time; it simply ships it back to the agent so the LLM sees
  *chunk + parent context* rather than the chunk in isolation.

- **Hybrid scoring.** Each chunk is scored with a weighted sum of a
  **keyword Jaccard** score over the chunk's pre-extracted ``keywords``
  list and a **semantic** score computed as the normalised Hamming
  distance between the query's embedding hash and the chunk's. The
  weights are :data:`KEYWORD_WEIGHT` (``0.4``) and
  :data:`SEMANTIC_WEIGHT` (``0.6``).

- **Citation-ready metadata.** ``path``, ``section``, ``title``, and a
  stable ``chunk_id`` ride along on every ``Document.metadata`` so the
  ``format_answer_with_citations`` tool can render ``[path#section]``
  references for the agent's answer.

The embedding hash is a deterministic stand-in (defined in
``scripts/build_index.py``). The upgrade path to real embeddings —
plug in :class:`ajolopy.rag.QdrantRetriever` or
:class:`ajolopy.rag.PgvectorRetriever` and replace the hash with a real
vector — is documented in the spec and in the README. The agent layer
needs zero changes to switch backends.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

from ajolopy.rag import Document, RetrievalHit, Retriever
from contextual_rag.scripts_runtime import content_tokens, embedding_hash, tokenise

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["KEYWORD_WEIGHT", "SEMANTIC_WEIGHT", "ContextualRagRetriever"]


#: Weight of the keyword-Jaccard component in the final hybrid score.
KEYWORD_WEIGHT: float = 0.4

#: Weight of the embedding-hash component in the final hybrid score.
#: ``KEYWORD_WEIGHT + SEMANTIC_WEIGHT == 1.0`` by construction.
SEMANTIC_WEIGHT: float = 0.6


_HASH_BITS: int = 16


def _hamming_distance(a: str, b: str) -> int:
    """Bit-positions where the two equal-length hash strings differ."""
    return sum(ch_a != ch_b for ch_a, ch_b in zip(a, b, strict=True))


def _keyword_score(query_tokens: set[str], chunk_keywords: list[str]) -> float:
    """Jaccard overlap between ``query_tokens`` and ``chunk_keywords``."""
    if not query_tokens or not chunk_keywords:
        return 0.0
    chunk_set = set(chunk_keywords)
    intersection = len(query_tokens & chunk_set)
    if intersection == 0:
        return 0.0
    union = len(query_tokens | chunk_set)
    return intersection / float(union)


def _semantic_score(query_hash: str, chunk_hash: str) -> float:
    """Normalised Hamming similarity between two 16-bit hash strings."""
    if len(query_hash) != _HASH_BITS or len(chunk_hash) != _HASH_BITS:
        return 0.0
    distance = _hamming_distance(query_hash, chunk_hash)
    return 1.0 - distance / float(_HASH_BITS)


class ContextualRagRetriever(Retriever):
    """Hybrid (keyword + hash) retriever over a contextual-chunk index.

    Construct empty and call :meth:`index`, or use :meth:`from_jsonl`
    to load a pre-built snapshot at boot.
    """

    def __init__(self) -> None:
        self._docs: list[Document] = []

    @classmethod
    def from_jsonl(cls, path: Path | str) -> ContextualRagRetriever:
        """Build a retriever from a JSONL index file.

        Each line is a JSON object with ``path``, ``chunk_id``,
        ``title``, ``section``, ``context_summary``, ``text``,
        ``keywords``, and ``embedding_hash`` fields. Missing files
        return an empty retriever (rather than raising) so the smoke
        test can run before the build script.
        """
        retriever = cls()
        snapshot = Path(path)
        if not snapshot.is_file():
            return retriever
        documents: list[Document] = []
        for raw_line in snapshot.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            raw: object = json.loads(line)
            if not isinstance(raw, dict):
                continue
            record = cast("dict[str, object]", raw)
            chunk_id = record.get("chunk_id")
            text = record.get("text")
            if not isinstance(chunk_id, str) or not isinstance(text, str):
                continue
            metadata: dict[str, object] = {
                "path": str(record.get("path", "")),
                "title": str(record.get("title", "")),
                "section": str(record.get("section", "")),
                "context_summary": str(record.get("context_summary", "")),
                "embedding_hash": str(record.get("embedding_hash", "")),
            }
            raw_keywords = record.get("keywords")
            if isinstance(raw_keywords, list):
                metadata["keywords"] = [str(token) for token in cast("list[object]", raw_keywords)]
            documents.append(Document(id=chunk_id, text=text, metadata=metadata))
        retriever._docs.extend(documents)
        return retriever

    @override
    async def index(self, documents: Iterable[Document]) -> None:
        """Upsert ``documents`` by :attr:`Document.id`."""
        incoming = list(documents)
        existing_ids = {doc.id for doc in incoming}
        self._docs = [doc for doc in self._docs if doc.id not in existing_ids]
        self._docs.extend(incoming)

    @override
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
        """Return the top ``k`` hits scored by the hybrid formula.

        Score = ``KEYWORD_WEIGHT * jaccard + SEMANTIC_WEIGHT * hamming``.
        Documents with a zero hybrid score are filtered out so the LLM
        never sees pure noise.
        """
        if k <= 0:
            return []
        query_keywords = self._query_keywords(text)
        query_hash = embedding_hash(text)
        scored: list[RetrievalHit] = []
        for doc in self._docs:
            metadata = doc.metadata if isinstance(doc.metadata, dict) else {}
            raw_keywords = metadata.get("keywords", [])
            chunk_keywords: list[str] = (
                [str(token) for token in cast("list[object]", raw_keywords)]
                if isinstance(raw_keywords, list)
                else []
            )
            chunk_hash = str(metadata.get("embedding_hash", ""))
            kw = _keyword_score(query_keywords, chunk_keywords)
            sem = _semantic_score(query_hash, chunk_hash)
            score = KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem
            if score <= 0.0:
                continue
            scored.append(RetrievalHit(document=doc, score=score))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]

    @override
    async def clear(self) -> None:
        """Drop every indexed document."""
        self._docs = []

    def __len__(self) -> int:
        return len(self._docs)

    @staticmethod
    def _query_keywords(text: str) -> set[str]:
        """Tokenise the query the same way the indexer scores keywords."""
        return set(content_tokens(tokenise(text)))
