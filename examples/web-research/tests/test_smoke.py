"""Smoke test — verifies the example imports and the decorators land.

The test deliberately does NOT call any LLM provider, does NOT call
the real Tavily API, and does NOT spin up the HTTP server. It only
asserts decoration-time metadata, Tavily-wrapper invariants, and one
end-to-end-ish exercise of the ``format_citations`` path against the
fake Tavily client installed by ``conftest.py``. No real network calls.
"""

import asyncio

import pytest
from web_research.agents.researcher import (
    Researcher,
    ResearchRequest,
)
from web_research.app_module import AppModule
from web_research.tavily import (
    SearchResult,
    TavilyClient,
    TavilyConfigError,
    get_client,
)

from ajolopy import AjolopyFactory


def test_researcher_is_decorated() -> None:
    """``Researcher`` survives import and exposes ``run`` / ``stream``."""
    assert hasattr(Researcher, "_agent_runtime")
    assert callable(getattr(Researcher, "run", None))
    assert callable(getattr(Researcher, "stream", None))


def test_search_web_tool_is_registered() -> None:
    """``Researcher.search_web`` carries the ``@Tool`` marker."""
    assert hasattr(Researcher.search_web, "__ajolopy_tool__")


def test_format_citations_tool_is_registered() -> None:
    """``Researcher.format_citations`` carries the ``@Tool`` marker."""
    assert hasattr(Researcher.format_citations, "__ajolopy_tool__")


def test_research_request_is_a_pydantic_model() -> None:
    """``ResearchRequest`` validates against the expected wire shape."""
    request = ResearchRequest.model_validate({"question": "what's new in Python 3.14?"})
    assert request.question == "what's new in Python 3.14?"


def test_stream_route_is_registered() -> None:
    """``Researcher.respond`` carries ``@Stream("/chat")`` metadata."""
    method = Researcher.respond
    metadata = getattr(method, "_ajolopy_stream", None)
    assert metadata is not None, "expected @Stream metadata on Researcher.respond"
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
            f"Expected /chat mounted on web-research app; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()


def test_tavily_client_from_env_raises_on_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``TavilyClient.from_env`` fails loudly when the env var is empty."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(TavilyConfigError):
        TavilyClient.from_env()


def test_tavily_client_direct_construction_rejects_empty_key() -> None:
    """``TavilyClient`` direct construction rejects an empty key string."""
    with pytest.raises(TavilyConfigError):
        TavilyClient(api_key="")


def test_get_client_returns_installed_fake() -> None:
    """The conftest-installed fake is the active Tavily client."""
    client = get_client()
    # The fake satisfies the protocol structurally — checking the
    # ``search`` attribute is enough; the runtime ``isinstance`` check
    # on Protocol requires ``@runtime_checkable`` which we deliberately
    # do not enable (we want pyright to enforce structural conformance
    # at the call site, not the runtime).
    assert hasattr(client, "search")
    assert callable(client.search)


def test_format_citations_renders_sources_section() -> None:
    """``format_citations`` appends a Markdown source bullet list."""
    rendered = Researcher().format_citations(
        "Python 3.14 ships PEP 649 deferred annotations by default.",
        [
            {
                "title": "Python 3.14 release notes",
                "url": "https://docs.python.org/3/whatsnew/3.14.html",
                "snippet": "...",
            }
        ],
    )
    assert "Sources:" in rendered
    assert "https://docs.python.org/3/whatsnew/3.14.html" in rendered
    assert "[Python 3.14 release notes]" in rendered


def test_format_citations_drops_invalid_records() -> None:
    """A source missing ``title`` or ``url`` is silently dropped."""
    rendered = Researcher().format_citations(
        "An answer with no usable sources.",
        [{"title": "broken"}],  # no ``url`` — must be dropped
    )
    # No bullets means we return the answer verbatim.
    assert rendered == "An answer with no usable sources."


def test_search_web_round_trips_through_fake_tavily() -> None:
    """The ``search_web`` ``@Tool`` reaches the conftest-installed fake.

    End-to-end-ish exercise of the injection seam: call the tool body
    directly, assert it routes to the fake, and assert the result is the
    canned :class:`SearchResult` list. No real HTTP call happens.
    """

    async def run() -> list[SearchResult]:
        return await Researcher().search_web("python 3.14", max_results=2)

    results = asyncio.run(run())
    assert len(results) == 2
    assert all(isinstance(hit, SearchResult) for hit in results)
    assert all("http" in hit["url"] for hit in results)


def test_format_citations_composes_with_search_web_output() -> None:
    """The two ``@Tool``s compose: search returns dicts, format consumes them."""

    async def run() -> str:
        results = await Researcher().search_web("python 3.14", max_results=2)
        return Researcher().format_citations(
            "Python 3.14 ships PEP 649 deferred annotations by default.",
            list(results),
        )

    rendered = asyncio.run(run())
    assert "Sources:" in rendered
    assert "https://" in rendered
