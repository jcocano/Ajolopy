"""Agents wired into the contextual-rag example's root ``@Module``.

Currently a single agent — :class:`ResearcherAgent` — which exposes
the contextual + hybrid RAG pipeline through two ``@Tool`` methods and
one ``@Stream("/chat")`` endpoint.
"""

from contextual_rag.agents.researcher import ChatRequest, ResearcherAgent

__all__ = ["ChatRequest", "ResearcherAgent"]
