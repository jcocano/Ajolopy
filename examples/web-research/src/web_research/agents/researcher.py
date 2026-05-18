"""The ``Researcher`` — one ``@Agent`` + two ``@Tool``s + one ``@Stream``.

The agent answers research questions by calling Tavily's web search API
through the :func:`search_web` tool, then optionally folding the
returned sources into a Markdown-cited answer through the pure-Python
:func:`format_citations` tool. The system prompt instructs the model to
quote URLs verbatim.

Drift note — observability:
    ``@Agent`` does not accept ``trace=`` in v0.1; OpenTelemetry
    instrumentation is always-on and cheap when no SDK is installed.
    Backend selection happens at the SDK layer via standard OTel env
    vars (``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``, ...).

Drift note — HTTP-client injection seam:
    ``@Stream`` mounts the agent class with ``cls()``; there is no
    constructor-injection seam at the route layer in v0.1. The tool
    method calls :func:`~web_research.tavily.get_client` to grab the
    active client, which lets the smoke test override the singleton via
    :func:`~web_research.tavily.set_client_for_tests` before importing
    the agent. Same pattern as the docsbot retriever singleton.
"""

# NOTE: ``AsyncGenerator`` MUST be imported at runtime (not under
# ``if TYPE_CHECKING:``). Python 3.14 + PEP 649 defers annotation
# evaluation until something calls ``get_annotations()`` /
# ``inspect.signature()``; the framework's ``@Stream`` mount path does
# exactly that on the ``respond`` handler below to wire up the route.
# If this symbol is only visible to static analysers, the mount step
# explodes with ``NameError: name 'AsyncGenerator' is not defined`` at
# server boot — a regression that first surfaced post-AJ-87.
from collections.abc import AsyncGenerator  # noqa: TC003
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body
from web_research.tavily import SearchResult, get_client


class ResearchRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint."""

    question: str


@Agent(
    model="claude-opus-4-7",
    system=(
        "You research and cite web sources. Always quote URLs. "
        "When the user asks a question that needs up-to-date information, "
        "call the search_web tool first, then ground every claim you make "
        "in the snippets you got back. After answering, you may call "
        "format_citations to render a clean Markdown-cited version of the "
        "answer. If the search returns no relevant results, say so plainly "
        "instead of inventing facts."
    ),
)
class Researcher:
    """The on-call web research assistant."""

    @Tool
    async def search_web(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search the web for fresh, source-cited snippets matching ``query``.

        Returns up to ``max_results`` (capped at 10) hits, each a dict
        with ``title``, ``url``, and ``snippet`` keys ordered from most
        to least relevant. Prefer 3-5 results to keep token usage low.
        """
        client = get_client()
        return await client.search(query, max_results=max_results)

    @Tool
    def format_citations(self, answer: str, sources: list[dict[str, str]]) -> str:
        """Render ``answer`` with Markdown footnotes pointing at ``sources``.

        ``sources`` is a list of records with ``title`` and ``url`` keys
        (the same shape :func:`search_web` returns). The function appends
        a ``Sources:`` section with one bullet per source in the order
        passed. Sources without both keys are skipped silently — better
        to drop than to render a broken link.
        """
        bullets: list[str] = []
        for source in sources:
            title = source.get("title")
            url = source.get("url")
            if not title or not url:
                continue
            bullets.append(f"- [{title}]({url})")
        if not bullets:
            return answer
        sources_section = "\n".join(bullets)
        return f"{answer}\n\nSources:\n{sources_section}"

    @Stream("/chat")
    async def respond(self, body: Annotated[ResearchRequest, Body()]) -> AsyncGenerator[str]:
        """Stream the research reply over SSE."""
        # ``self.stream`` is injected by ``@Agent`` at decoration time;
        # static analysers cannot see the attribute, so we silence the
        # missing-attribute warning here. Same pattern as the framework's
        # own composability tests.
        async for chunk in self.stream(body.question):  # type: ignore[attr-defined]
            yield chunk
