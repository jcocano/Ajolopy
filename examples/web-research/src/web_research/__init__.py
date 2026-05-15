"""Runnable example: a web research agent that calls Tavily via ``@Tool`` (AJ-65).

The package mirrors the in-repo example layout one-to-one:

- :mod:`web_research.tavily` — thin ``httpx``-backed wrapper for the
  Tavily ``POST /search`` endpoint. Module-level singleton so the smoke
  test can swap a fake client in via :func:`tavily.set_client_for_tests`.
- :mod:`web_research.agents.researcher` — the ``Researcher`` ``@Agent``
  with two ``@Tool`` methods (``search_web`` calls Tavily,
  ``format_citations`` is pure-Python) and a ``@Stream("/chat")`` handler.
- :mod:`web_research.app_module` — the root ``@Module`` that wires the
  agent into the DI container.
- :mod:`web_research.main` — the ASGI entry point used by ``ajolopy dev``.
"""

# Side-effect import — registers ``AnthropicProvider`` under the
# ``"anthropic"`` routing key so ``@Agent(model="claude-...")`` can
# resolve at decoration time without raising
# ``ProviderNotRegisteredError``. See
# ``ajolopy/providers/anthropic/__init__.py``.
import ajolopy.providers.anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
