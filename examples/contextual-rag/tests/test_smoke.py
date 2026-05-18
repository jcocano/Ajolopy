"""Smoke test — verifies the example imports and the decorators land.

Network-free and deterministic. The test does NOT call any LLM
provider, does NOT ``monkeypatch`` the SDK, and does NOT spin up the
HTTP server. It only asserts decoration-time metadata, retriever
construction off the checked-in ``data/index.jsonl``, and that the
``/chat`` route is registered — enough to catch import-time regressions
when the upstream framework moves.
"""

import asyncio

import pytest
from contextual_rag.agents.researcher import (
    ChatRequest,
    ResearcherAgent,
    get_retriever,
)
from contextual_rag.app_module import AppModule
from contextual_rag.retriever import (
    KEYWORD_WEIGHT,
    SEMANTIC_WEIGHT,
    ContextualRagRetriever,
)
from contextual_rag.scripts_runtime import embedding_hash

from ajolopy import AjolopyFactory
from ajolopy.rag import Retriever


def test_researcher_agent_is_decorated() -> None:
    """``ResearcherAgent`` survives import and exposes ``run`` / ``stream``."""
    assert hasattr(ResearcherAgent, "_agent_runtime")
    assert callable(getattr(ResearcherAgent, "run", None))
    assert callable(getattr(ResearcherAgent, "stream", None))


def test_both_tools_are_registered() -> None:
    """Both ``@Tool`` methods carry the ``__ajolopy_tool__`` marker."""
    assert hasattr(ResearcherAgent.retrieve_with_context, "__ajolopy_tool__")
    assert hasattr(ResearcherAgent.format_answer_with_citations, "__ajolopy_tool__")


def test_chat_request_is_a_pydantic_model() -> None:
    """The ``ChatRequest`` body validates against the expected shape."""
    request = ChatRequest.model_validate({"message": "How much PTO can I take?"})
    assert request.message == "How much PTO can I take?"


def test_contextual_rag_retriever_is_a_retriever_subclass() -> None:
    """The contextual retriever subclasses the AJ-62 ``Retriever`` ABC."""
    assert issubclass(ContextualRagRetriever, Retriever)


def test_retriever_loads_snapshot() -> None:
    """The checked-in JSONL snapshot loads at least 10 chunks."""
    retriever = get_retriever()
    assert isinstance(retriever, ContextualRagRetriever)
    # The synthetic handbook ships 8 files with multiple sections each.
    assert len(retriever) >= 10


@pytest.mark.asyncio
async def test_retriever_query_returns_hits_for_known_topic() -> None:
    """A query whose tokens overlap the handbook returns a positive hit."""
    retriever = get_retriever()
    hits = await retriever.query("vacation and paid time off", k=3)
    assert len(hits) >= 1
    assert hits[0].score > 0.0
    # The top hit's chunk metadata should carry the citation-ready
    # ``path`` + ``section`` fields the formatter tool consumes.
    metadata = hits[0].document.metadata
    assert isinstance(metadata, dict)
    assert metadata.get("path", "").startswith("handbook/")
    assert metadata.get("section")


def test_hybrid_weights_sum_to_one() -> None:
    """The 40/60 keyword/semantic split is the agreed-upon weighting."""
    assert KEYWORD_WEIGHT + SEMANTIC_WEIGHT == 1.0
    assert KEYWORD_WEIGHT == 0.4
    assert SEMANTIC_WEIGHT == 0.6


def test_embedding_hash_is_deterministic_and_16_bits() -> None:
    """The embedding hash is reproducible and 16 bits wide."""
    a = embedding_hash("paid time off policy at Tlaltipac")
    b = embedding_hash("paid time off policy at Tlaltipac")
    assert a == b
    assert len(a) == 16
    assert set(a).issubset({"0", "1"})


def test_stream_route_is_registered() -> None:
    """``ResearcherAgent.respond`` carries ``@Stream("/chat")`` metadata."""
    method = ResearcherAgent.respond
    metadata = getattr(method, "_ajolopy_stream", None)
    assert metadata is not None, "expected @Stream metadata on ResearcherAgent.respond"
    assert metadata.path == "/chat"
    assert metadata.method == "POST"


@pytest.mark.asyncio
async def test_app_boots_and_mounts_chat_route() -> None:
    """AJ-98 regression: ``AjolopyFactory.create`` must boot + mount ``/chat``.

    Drives the agent's ``@Stream("/chat")`` handler — whose
    ``AsyncGenerator`` return annotation is the one that previously
    crashed under PEP 649 — through the framework's ``mount_streams``
    path. The assertion is that the route lands on ``app.http``;
    without the AJ-98 fix the factory raises ``NameError`` before we
    ever get here.
    """
    app = await AjolopyFactory.create(AppModule)
    try:
        paths = {getattr(route, "path", "") for route in app.http.routes}
        assert "/chat" in paths, (
            f"Expected /chat mounted on contextual-rag app; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()


def test_retriever_round_trip() -> None:
    """``index`` then ``query`` returns the indexed document."""

    async def run() -> None:
        retriever = ContextualRagRetriever()
        from ajolopy.rag import Document

        # The Document needs an ``embedding_hash`` in its metadata so the
        # semantic component of the hybrid score can fire. We compute the
        # hash with the same helper the indexer uses.
        text = "agents stream tokens over server-sent events"
        await retriever.index(
            [
                Document(
                    id="d-1",
                    text=text,
                    metadata={
                        "path": "synthetic.md",
                        "section": "Overview",
                        "title": "Synthetic",
                        "context_summary": "Round-trip test fixture.",
                        "keywords": ["agents", "stream", "tokens", "server", "events"],
                        "embedding_hash": embedding_hash(text),
                    },
                )
            ]
        )
        hits = await retriever.query("agents and tokens", k=1)
        assert len(hits) == 1
        assert hits[0].document.id == "d-1"
        await retriever.clear()
        assert len(retriever) == 0

    asyncio.run(run())
