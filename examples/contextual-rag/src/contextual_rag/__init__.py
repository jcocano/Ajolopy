"""Launch example #5 — the contextual RAG agent (AJ-67).

The package showcases production-grade retrieval-augmented generation
on top of the v0.1 Ajolopy primitives with three quality bumps over
``dogfood/docsbot``:

- :mod:`contextual_rag.retriever` — :class:`ContextualRagRetriever`
  subclasses :class:`ajolopy.rag.Retriever` (the AJ-62 escape hatch),
  loads chunks from ``data/index.jsonl``, and scores hits with a
  weighted sum of a keyword-Jaccard score and a deterministic
  embedding-hash similarity (40 / 60 split). Offline, deterministic,
  zero external services.
- :mod:`contextual_rag.agents.researcher` — the ``ResearcherAgent``
  ``@Agent`` with two ``@Tool`` methods (``retrieve_with_context`` and
  ``format_answer_with_citations``) and one ``@Stream("/chat")``
  endpoint that streams the LLM's grounded, citation-rich answer.
- :mod:`contextual_rag.app_module` — root ``@Module`` wiring the
  researcher into the DI container.
- :mod:`contextual_rag.main` — ASGI entry point used by
  ``ajolopy dev``.

The chunk index ships ``context_summary``, ``section``, and
``embedding_hash`` per record so the retriever can do contextual
chunking (the LLM sees *chunk + parent context*), hybrid scoring, and
cite ``[path#section]``-style sources. See ``scripts/build_index.py``
for the indexer and ``specs/example-contextual-rag.md`` for the
upgrade path to real embeddings.
"""

# Side-effect import — registers ``AnthropicProvider`` under the
# ``"anthropic"`` routing key so ``@Agent(model="claude-...")`` resolves
# at decoration time without raising ``ProviderNotRegisteredError``.
# Same pattern the docsbot and support-agent examples use.
import ajolopy.providers.anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
