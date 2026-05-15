"""Root ``@Module`` for the contextual-rag example.

The module declares :class:`~contextual_rag.agents.researcher.ResearcherAgent`
as the sole agent. The retriever singleton lives at module scope in
:mod:`contextual_rag.agents.researcher` (the ``@Stream`` mount
instantiates the agent class with ``cls()``, so the tool layer cannot
consume a constructor-injected retriever in v0.1).
"""

from ajolopy import Module
from contextual_rag.agents.researcher import ResearcherAgent


@Module(agents=[ResearcherAgent])
class AppModule:
    """Root module — one agent, one ``@Stream("/chat")`` endpoint."""


__all__ = ["AppModule"]
