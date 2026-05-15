"""In-memory ``Retriever`` over a JSONL snapshot of the Ajolopy docs.

This is the documented **AJ-62 escape hatch**: the
:class:`~ajolopy.rag.Retriever` ABC ships two production-grade backends
(:class:`~ajolopy.rag.QdrantRetriever`, :class:`~ajolopy.rag.PgvectorRetriever`)
that both require external services. For the v0.1 dogfood demo we want
the app to boot offline with zero infra, so the docsbot subclasses the
ABC with a pure-Python implementation:

- ``index(documents)`` keeps the ``Document`` list in process memory.
- ``query(text, k=5)`` scores every document by lowercase-tokenised
  bag-of-words overlap with the query and returns the top ``k`` hits.
- ``clear()`` empties the internal list.

The keyword score is a deliberate v0.1 trade-off — wording overlap
between question and docs is enough for the launch demo. The upgrade
path to embedding-based retrieval is documented in the README under
"Future enhancements" (drop in ``QdrantRetriever`` / ``PgvectorRetriever``
and feed the index step a real embedding model).
"""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

from ajolopy.rag import Document, RetrievalHit, Retriever

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["InMemoryDocsRetriever"]


# Word-boundary tokenisation: lowercase, split on non-word characters.
# The regex is module-scope so every call shares the compiled object.
_TOKEN_RE = re.compile(r"\w+")


def _tokenise(text: str) -> set[str]:
    """Return the lowercase set of word tokens in ``text``."""
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


class InMemoryDocsRetriever(Retriever):
    """Keyword-overlap retriever backed by a Python list.

    Construct with :meth:`from_jsonl` to load a docs snapshot at boot,
    or instantiate empty and call :meth:`index` programmatically.
    """

    def __init__(self) -> None:
        self._docs: list[Document] = []

    @classmethod
    def from_jsonl(cls, path: Path | str) -> InMemoryDocsRetriever:
        """Build a retriever from a JSONL snapshot.

        Each line is expected to be a JSON object with ``id``, ``path``,
        ``title``, and ``text`` keys. ``path`` + ``title`` are folded
        into ``Document.metadata`` so the tool layer can quote them on
        the wire.
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
            doc_id = record.get("id")
            text = record.get("text")
            if not isinstance(doc_id, str) or not isinstance(text, str):
                continue
            metadata: dict[str, object] = {}
            doc_path = record.get("path")
            if isinstance(doc_path, str):
                metadata["path"] = doc_path
            title = record.get("title")
            if isinstance(title, str):
                metadata["title"] = title
            documents.append(Document(id=doc_id, text=text, metadata=metadata))
        retriever._docs.extend(documents)
        return retriever

    @override
    async def index(self, documents: Iterable[Document]) -> None:
        """Append ``documents`` to the in-memory store (upsert by id)."""
        incoming = list(documents)
        existing_ids = {doc.id for doc in incoming}
        # Upsert semantics: drop any prior copy of an incoming id, then append.
        self._docs = [doc for doc in self._docs if doc.id not in existing_ids]
        self._docs.extend(incoming)

    @override
    async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
        """Return the top ``k`` hits scored by keyword overlap.

        Score is ``|q ∩ d| / max(1, |q|)`` — the fraction of the query
        tokens that also appear in the document. Documents with zero
        overlap are filtered out so the LLM never sees noise on
        no-overlap queries.
        """
        if k <= 0:
            return []
        query_tokens = _tokenise(text)
        if not query_tokens:
            return []
        normaliser = float(len(query_tokens))
        scored: list[RetrievalHit] = []
        for doc in self._docs:
            doc_tokens = _tokenise(doc.text)
            overlap = len(query_tokens & doc_tokens)
            if overlap == 0:
                continue
            scored.append(RetrievalHit(document=doc, score=overlap / normaliser))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]

    @override
    async def clear(self) -> None:
        """Drop every indexed document."""
        self._docs = []

    def __len__(self) -> int:
        return len(self._docs)
