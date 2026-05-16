"""The ``ResearcherAgent`` — one ``@Agent`` + two ``@Tool``s + one ``@Stream``.

The agent answers questions against the sample Tlaltipac handbook
loaded from ``data/index.jsonl``. The system prompt biases the model
toward calling **both** tools per turn:

1. ``retrieve_with_context`` — fetches the top hits from the hybrid
   retriever and ships back each chunk's text with its
   ``context_summary`` prepended (this is the "contextual chunking"
   pay-off — the LLM sees *chunk + parent context*, not the chunk in
   isolation).
2. ``format_answer_with_citations`` — appends a ``Sources:`` block to
   the model's draft answer with ``[path#section]`` references for
   every retrieved chunk. The eval suite's ``has_citations`` /
   ``right_section`` metrics fail when this tool is skipped.

Drift note — observability:
    ``@Agent`` does not accept ``trace=`` in v0.1; OpenTelemetry
    instrumentation is always-on and cheap when no SDK is installed.
    Backend selection happens at the SDK layer via standard OTel env
    vars (``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``).
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body
from contextual_rag.retriever import ContextualRagRetriever

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ---------------------------------------------------------------------------
# Retriever singleton.
#
# ``@Stream`` mounts instantiate the agent class with ``cls()`` (no
# constructor-injected dependencies at the stream layer in v0.1), so
# the agent's tool methods cannot accept a retriever as an ``__init__``
# argument. A module-level lazy singleton keyed off the JSONL snapshot
# keeps the agent class zero-arg.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DATA_PATH = _PROJECT_ROOT / "data" / "index.jsonl"
_retriever: ContextualRagRetriever | None = None


def get_retriever() -> ContextualRagRetriever:
    """Return the shared retriever, building it on first access."""
    global _retriever
    if _retriever is None:
        _retriever = ContextualRagRetriever.from_jsonl(_DATA_PATH)
    return _retriever


class ChatRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint."""

    message: str


_SYSTEM_PROMPT = (
    "You are the Tlaltipac handbook assistant. The user is an employee or "
    "candidate asking questions about how the company operates. Workflow "
    "for every turn:\n\n"
    "  1. Call `retrieve_with_context` with the user's question and "
    "     `top_k=4`. The tool returns chunks of the handbook with their "
    "     parent-section context prepended; ground every claim in those "
    "     chunks and quote them when it adds clarity.\n"
    "  2. Compose a concise, accurate answer (one or two short "
    "     paragraphs).\n"
    "  3. Call `format_answer_with_citations` with your draft answer and "
    "     the list of chunks you used. Return the tool's output verbatim "
    "     as your final response so the user sees the citation block.\n\n"
    "If the retrieved chunks do not cover the question, say so plainly "
    "instead of guessing. Never invent a citation; only cite a chunk "
    "that the retrieve tool actually returned."
)


@Agent(
    model="claude-opus-4-7",
    system=_SYSTEM_PROMPT,
    fallback="claude-haiku-4-5",
)
class ResearcherAgent:
    """The Tlaltipac handbook assistant — contextual + hybrid RAG."""

    @Tool
    async def retrieve_with_context(self, query: str, top_k: int = 4) -> list[dict[str, object]]:
        """Look up handbook chunks relevant to ``query``.

        Returns a list ordered by hybrid score (most relevant first).
        Each entry has ``path``, ``section``, ``title``, ``score``, and
        a ``text`` field that already has the chunk's
        ``context_summary`` prepended so the agent reads *chunk +
        parent context* without an extra round-trip.

        ``top_k`` caps the number of returned chunks; the agent should
        pass a small value (3-5) to keep token usage low.
        """
        retriever = get_retriever()
        hits = await retriever.query(query, k=top_k)
        results: list[dict[str, object]] = []
        for hit in hits:
            metadata = hit.document.metadata if isinstance(hit.document.metadata, dict) else {}
            path = str(metadata.get("path", ""))
            section = str(metadata.get("section", ""))
            title = str(metadata.get("title", ""))
            context_summary = str(metadata.get("context_summary", ""))
            text = hit.document.text
            contextualised = f"Context: {context_summary}\n\n{text}" if context_summary else text
            results.append(
                {
                    "path": path,
                    "section": section,
                    "title": title,
                    "score": round(hit.score, 4),
                    "text": contextualised,
                }
            )
        return results

    @Tool
    async def format_answer_with_citations(
        self, answer: str, chunks: list[dict[str, object]]
    ) -> str:
        """Append a ``Sources:`` block to ``answer``.

        ``chunks`` is the list returned by ``retrieve_with_context``.
        Each citation is rendered as ``[path#section]`` so a reader (or
        the ``has_citations`` deterministic eval metric) can confirm
        the answer is grounded in a specific section of the corpus.

        Duplicate ``path#section`` references are collapsed so the
        block stays compact when the agent reuses the same chunk
        multiple times in a single answer.
        """
        stripped = answer.rstrip()
        if not chunks:
            return f"{stripped}\n\nSources: (no chunks retrieved)"
        seen: set[str] = set()
        citations: list[str] = []
        for chunk in chunks:
            path = str(chunk.get("path", "")).strip()
            section = str(chunk.get("section", "")).strip()
            if not path:
                continue
            reference = f"[{path}#{section}]" if section else f"[{path}]"
            if reference in seen:
                continue
            seen.add(reference)
            citations.append(reference)
        if not citations:
            return f"{stripped}\n\nSources: (no chunks retrieved)"
        return f"{stripped}\n\nSources:\n" + "\n".join(f"- {ref}" for ref in citations)

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[str]:
        """Stream a citation-rich handbook answer over SSE."""
        # ``self.stream`` is injected by ``@Agent`` at decoration time;
        # static analysers cannot see the attribute, so we silence the
        # missing-attribute warning here (same pattern as the support
        # and docsbot examples).
        async for chunk in self.stream(body.message):  # type: ignore[attr-defined]
            yield chunk
