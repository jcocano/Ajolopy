"""Thin ``httpx``-backed wrapper for the Tavily search REST API.

This module is intentionally narrow: one ``TavilyClient.search(...)``
call that posts to ``https://api.tavily.com/search`` and returns a flat
list of ``{"title", "url", "snippet"}`` dicts. No SDK dependency, no
result re-ranking, no caching. The wedge lesson the example teaches is
"wire a third-party HTTP API as a ``@Tool``"; everything beyond that is
out of scope for v0.1.

The module exposes a **process-wide singleton getter** so the agent's
``@Tool`` method can grab the active client at call time. The
:func:`set_client_for_tests` helper lets the smoke test override the
singleton with a fake before the agent module is imported. The pattern
matches the retriever singleton in ``dogfood/docsbot/agents/docs.py``.
"""

import os
from typing import TYPE_CHECKING, Protocol, cast

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "SearchResult",
    "TavilyClient",
    "TavilyConfigError",
    "TavilyHTTPError",
    "TavilyProtocol",
    "TavilyResponseError",
    "get_client",
    "set_client_for_tests",
]


# ---------------------------------------------------------------------------
# Public errors.
# ---------------------------------------------------------------------------


class TavilyConfigError(RuntimeError):
    """Raised when ``TAVILY_API_KEY`` is missing at call time."""


class TavilyHTTPError(RuntimeError):
    """Raised when Tavily returns a non-2xx HTTP response."""


class TavilyResponseError(RuntimeError):
    """Raised when Tavily's response body cannot be parsed as expected."""


# ---------------------------------------------------------------------------
# Data shape.
# ---------------------------------------------------------------------------


class SearchResult(dict[str, str]):
    """A single search hit on the wire.

    Subclassing :class:`dict` keeps the shape JSON-serialisable without
    adding a Pydantic dependency to the tool layer. The keys are always
    ``title``, ``url``, ``snippet``.
    """


# ---------------------------------------------------------------------------
# Tavily HTTP client.
# ---------------------------------------------------------------------------


class TavilyProtocol(Protocol):
    """Structural interface a Tavily client must implement.

    Both the real :class:`TavilyClient` and any test fake satisfy this
    protocol; the agent's ``@Tool`` only depends on the ``search`` method
    so static typing stays honest while the singleton swap remains
    cheap.
    """

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...


# Tavily's REST endpoint. Constant so a test (or a future self-hosted
# Tavily fork) can monkeypatch the URL without rewriting the client.
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Default HTTP timeout in seconds. Tavily's median response is well under
# a second; the cap is generous for cold connections without making a
# stuck request silently freeze the agent's tool loop.
DEFAULT_TIMEOUT_SECONDS = 15.0


class TavilyClient:
    """Async HTTP client over Tavily's ``POST /search`` endpoint.

    Construct via :meth:`from_env` to read ``TAVILY_API_KEY`` from the
    process environment, or instantiate directly with an explicit key for
    test setups that want to avoid environment leakage.
    """

    def __init__(self, api_key: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not api_key:
            raise TavilyConfigError(
                "TAVILY_API_KEY is empty. Set the env var or pass api_key= "
                "explicitly. Sign up at https://tavily.com to get a key."
            )
        self._api_key = api_key
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> TavilyClient:
        """Read ``TAVILY_API_KEY`` from the environment.

        Raises :class:`TavilyConfigError` if the variable is missing or
        empty, mirroring the framework's ``BaseConfig`` validation rule:
        fail loudly at construction time rather than at the first call
        site.
        """
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            raise TavilyConfigError(
                "TAVILY_API_KEY is not set. The web-research example needs "
                "a Tavily key to call the search API at runtime. Sign up at "
                "https://tavily.com, then add TAVILY_API_KEY=... to .env."
            )
        return cls(api_key=api_key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Run a search and return up to ``max_results`` hits.

        The wire shape is what Tavily documents for ``include_answer=False``:

        - ``query`` (required) — the search string.
        - ``max_results`` (1-10) — clamped to ``[1, 10]`` on the client side
          so the agent never asks for runaway pages.

        Returns a list of :class:`SearchResult` records with ``title``,
        ``url``, and ``snippet`` keys. The snippet text is the
        ``content`` field Tavily returns per hit.

        Raises:
            TavilyConfigError: API key empty at construction time (handled
                in :meth:`__init__`).
            TavilyHTTPError: Tavily returns a non-2xx response.
            TavilyResponseError: Body parsing fails or no ``results`` key.
        """
        clamped = max(1, min(int(max_results), 10))
        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": clamped,
            "search_depth": "basic",
            "include_answer": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            try:
                response = await http.post(TAVILY_SEARCH_URL, json=payload)
            except httpx.HTTPError as exc:
                raise TavilyHTTPError(f"Tavily request failed: {exc}") from exc

        if response.status_code >= 400:
            raise TavilyHTTPError(
                f"Tavily returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise TavilyResponseError(f"Tavily returned non-JSON body: {exc}") from exc

        if not isinstance(body, dict):
            raise TavilyResponseError("Tavily response is not a JSON object.")

        raw_results = cast("dict[str, object]", body).get("results")
        if not isinstance(raw_results, list):
            raise TavilyResponseError("Tavily response is missing a 'results' list.")

        return list(_normalise_results(cast("list[object]", raw_results)))


def _normalise_results(raw_results: Iterable[object]) -> Iterable[SearchResult]:
    """Drop malformed entries and coerce keys to ``title/url/snippet``.

    Tavily occasionally returns hits without one of ``title`` /
    ``content`` / ``url`` — we drop those instead of synthesising
    placeholder strings the model could hallucinate against.
    """
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        record = cast("dict[str, object]", raw)
        title = record.get("title")
        url = record.get("url")
        snippet = record.get("content") or record.get("snippet")
        if not isinstance(title, str) or not isinstance(url, str) or not isinstance(snippet, str):
            continue
        yield SearchResult(title=title, url=url, snippet=snippet)


# ---------------------------------------------------------------------------
# Process-wide singleton.
#
# ``@Stream`` mounts the agent class with ``cls()`` — there is no
# constructor-injection seam at the route layer in v0.1. The convention
# used by the in-repo examples (``dogfood/docsbot/agents/docs.py``) is a
# module-level singleton with a lazy getter; the smoke test overrides
# the singleton via :func:`set_client_for_tests` before the agent module
# is imported.
# ---------------------------------------------------------------------------

_client: TavilyProtocol | None = None


def get_client() -> TavilyProtocol:
    """Return the shared Tavily client, building it lazily from env on first access."""
    global _client
    if _client is None:
        _client = TavilyClient.from_env()
    return _client


def set_client_for_tests(client: TavilyProtocol | None) -> None:
    """Override the shared Tavily client (test seam).

    Passing ``None`` clears the singleton so the next :func:`get_client`
    call rebuilds from env. Real test suites pass a fake that implements
    :class:`TavilyProtocol`.
    """
    global _client
    _client = client
