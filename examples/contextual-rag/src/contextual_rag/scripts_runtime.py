"""Shared tokenisation + hashing helpers used at index and query time.

The contextual-rag example wants the **same** tokenisation, stopword
list, and embedding-hash function in two places:

- ``scripts/build_index.py`` runs at build time to populate every
  chunk's ``keywords`` and ``embedding_hash`` fields.
- :class:`contextual_rag.retriever.ContextualRagRetriever` runs at query
  time to hash the incoming user query so it can be compared against
  pre-computed chunk hashes.

Sharing the helpers from a single source-of-truth module keeps the
two pipelines in lockstep — drift between them would silently break
retrieval. The module lives inside the package (not under ``scripts/``)
so it survives ``uv sync`` + an editable install.
"""

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["STOPWORDS", "content_tokens", "embedding_hash", "tokenise"]


_TOKEN_RE = re.compile(r"\w+")


# Short, hand-tuned stopword list. Mirrors the one referenced from the
# spec; intentionally minimal because the keyword-Jaccard score is a
# tie-breaker for the hybrid retriever, not a full IR pipeline.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "this",
        "to",
        "was",
        "with",
        "you",
        "your",
        "we",
        "our",
        "ours",
        "any",
        "no",
        "not",
        "than",
        "then",
        "they",
        "those",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "must",
        "but",
        "before",
        "after",
        "during",
        "over",
        "under",
        "out",
        "off",
    }
)


def tokenise(text: str) -> list[str]:
    """Lowercase word-boundary tokens for ``text``."""
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def content_tokens(tokens: Iterable[str]) -> list[str]:
    """Drop stopwords and pure-digit tokens from ``tokens``."""
    return [t for t in tokens if t not in STOPWORDS and not t.isdigit()]


def embedding_hash(text: str) -> str:
    """Deterministic 16-bit ``"0"`` / ``"1"`` fingerprint of ``text``.

    See ``scripts/build_index.py`` for the pipeline rationale. The
    short version: sort the de-duplicated content-token set, SHA-256 the
    join, take the top 16 bits of the first 64 bits of the digest, and
    emit those bits as a string. Two chunks discussing the same topic
    share more bits than chunks on different topics.

    The function is a public helper because the retriever needs to
    compute the same hash for incoming queries. A real embedding model
    is a drop-in replacement (see the spec's "Upgrade path" section).
    """
    tokens = sorted(set(content_tokens(tokenise(text))))
    digest = hashlib.sha256(" ".join(tokens).encode("utf-8")).hexdigest()
    as_int = int(digest[:16], 16)
    top_bits = as_int >> 48
    return format(top_bits, "016b")
