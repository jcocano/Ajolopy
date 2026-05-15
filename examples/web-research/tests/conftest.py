"""Test-suite preamble for the web-research example.

Two responsibilities, executed at collection time before the smoke test
module is imported:

1.  Set dummy values for ``ANTHROPIC_API_KEY`` and ``TAVILY_API_KEY`` so
    importing the example's agents — which decorate at import time and
    instantiate the Anthropic provider — does not require a real key on
    a developer's first ``uv run pytest`` after cloning.

2.  Install a :class:`FakeTavilyClient` into the example's module-level
    singleton so the smoke test can exercise the tool wiring without any
    real network call. The fake records calls and returns a fixed
    snippet list per query.

The fake is exposed as a module-level constant (``FAKE_TAVILY_RESULTS``)
so individual test functions can assert on it without having to
re-fetch the singleton.
"""

import os

# Set env vars BEFORE any ``web_research.*`` module is imported. ``conftest.py``
# is evaluated by pytest at collection time, ahead of test modules.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy")
os.environ.setdefault("TAVILY_API_KEY", "test-dummy")

# Now safe to import the example's modules — the dummy keys satisfy
# decoration-time validation in the provider layer and let the Tavily
# wrapper construct itself if anything inadvertently triggers
# ``get_client()`` from env.
from web_research.tavily import (
    SearchResult,
    TavilyProtocol,
    set_client_for_tests,
)

FAKE_TAVILY_RESULTS: list[SearchResult] = [
    SearchResult(
        title="Python 3.14 release notes",
        url="https://docs.python.org/3/whatsnew/3.14.html",
        snippet="Python 3.14 ships PEP 649 deferred annotations as the default.",
    ),
    SearchResult(
        title="Real Python — what's new in Python 3.14",
        url="https://realpython.com/python-314/",
        snippet="A walkthrough of the new language features, performance work, and stdlib changes.",
    ),
]


class FakeTavilyClient:
    """In-memory Tavily stand-in.

    Satisfies :class:`TavilyProtocol` structurally — the agent's
    ``search_web`` tool only depends on ``async def search(...)``. The
    fake records the most recent call so a test can assert that the
    tool reached it.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Record the call and return a copy of :data:`FAKE_TAVILY_RESULTS`."""
        self.calls.append((query, max_results))
        # Slice off ``max_results`` so the contract matches the real
        # client's "up to N hits" guarantee.
        return list(FAKE_TAVILY_RESULTS[:max_results])


# Install the fake once at collection time. Individual tests can call
# ``set_client_for_tests(...)`` themselves to swap in a different fake.
_FAKE_INSTANCE: TavilyProtocol = FakeTavilyClient()
set_client_for_tests(_FAKE_INSTANCE)
