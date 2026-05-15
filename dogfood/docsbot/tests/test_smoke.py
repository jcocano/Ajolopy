"""Smoke test — verifies the docs bot imports and the decorators land.

The test deliberately does NOT call any LLM provider, does NOT
``monkeypatch`` the SDK, and does NOT spin up the HTTP server. It only
asserts decoration-time metadata, retriever construction, and that the
``/chat`` route is registered — enough to catch import-time regressions
when the upstream framework moves.
"""

import asyncio

import pytest
from docsbot.agents.docs import ChatRequest, DocsAgent, get_retriever
from docsbot.retriever import InMemoryDocsRetriever

from ajolopy.rag import Retriever


def test_docs_agent_is_decorated() -> None:
    """``DocsAgent`` survives import and exposes ``run`` / ``stream``."""
    assert hasattr(DocsAgent, "_agent_runtime")
    assert callable(getattr(DocsAgent, "run", None))
    assert callable(getattr(DocsAgent, "stream", None))


def test_retrieve_docs_tool_is_registered() -> None:
    """``DocsAgent.retrieve_docs`` carries the ``@Tool`` marker."""
    assert hasattr(DocsAgent.retrieve_docs, "__ajolopy_tool__")


def test_chat_request_is_a_pydantic_model() -> None:
    """The ``ChatRequest`` body validates against the expected shape."""
    request = ChatRequest.model_validate({"message": "What is @Agent?"})
    assert request.message == "What is @Agent?"


def test_in_memory_retriever_is_a_retriever_subclass() -> None:
    """The dogfood retriever subclasses the AJ-62 ``Retriever`` ABC."""
    assert issubclass(InMemoryDocsRetriever, Retriever)


def test_retriever_loads_snapshot() -> None:
    """The checked-in JSONL snapshot loads at least one document."""
    retriever = get_retriever()
    assert isinstance(retriever, InMemoryDocsRetriever)
    assert len(retriever) >= 1


@pytest.mark.asyncio
async def test_retriever_query_returns_hits_for_known_terms() -> None:
    """A query whose tokens appear in the docs returns at least one hit."""
    retriever = get_retriever()
    hits = await retriever.query("agent decorator", k=3)
    assert len(hits) >= 1
    assert hits[0].score > 0.0


def test_stream_route_is_registered() -> None:
    """``DocsAgent.respond`` carries ``@Stream("/chat")`` metadata."""
    method = DocsAgent.respond
    metadata = getattr(method, "_ajolopy_stream", None)
    assert metadata is not None, "expected @Stream metadata on DocsAgent.respond"
    assert metadata.path == "/chat"
    assert metadata.method == "POST"


def test_in_memory_retriever_round_trip() -> None:
    """``index`` then ``query`` returns the indexed document."""

    async def run() -> None:
        retriever = InMemoryDocsRetriever()
        from ajolopy.rag import Document

        await retriever.index(
            [
                Document(id="d-1", text="agents stream tokens over SSE"),
                Document(id="d-2", text="modules wire providers into the container"),
            ]
        )
        hits = await retriever.query("agents", k=1)
        assert len(hits) == 1
        assert hits[0].document.id == "d-1"
        await retriever.clear()
        assert len(retriever) == 0

    asyncio.run(run())
