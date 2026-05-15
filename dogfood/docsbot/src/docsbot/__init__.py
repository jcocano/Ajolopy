"""Dogfood app #1 — the Ajolopy docs bot (AJ-54).

The package answers questions about the Ajolopy framework using
Ajolopy's own primitives end-to-end:

- :mod:`docsbot.retriever` — an in-memory :class:`~ajolopy.rag.Retriever`
  subclass (the AJ-62 escape hatch) that loads chunks from a JSONL
  snapshot and scores hits with a keyword-overlap metric. Zero external
  services, deterministic, offline-friendly.
- :mod:`docsbot.agents.docs` — the ``DocsAgent`` ``@Agent`` with one
  ``@Tool`` (``retrieve_docs``) and one ``@Stream("/chat")`` handler
  that streams the LLM's grounded answer.
- :mod:`docsbot.app_module` — the root ``@Module`` that wires the agent
  + retriever into the DI container.
- :mod:`docsbot.main` — the ASGI entry point used by ``ajolopy dev``.
"""

# Side-effect import — registers ``AnthropicProvider`` under the
# ``"anthropic"`` routing key so ``@Agent(model="claude-...")`` can
# resolve at decoration time without raising
# ``ProviderNotRegisteredError``. See
# ``ajolopy/providers/anthropic/__init__.py``.
import ajolopy.providers.anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
