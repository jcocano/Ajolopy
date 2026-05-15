"""Root ``@Module`` for the docsbot dogfood app.

The module declares :class:`~docsbot.agents.docs.DocsAgent` as the sole
agent. The retriever singleton lives at module scope in
:mod:`docsbot.agents.docs` (the ``@Stream`` mount instantiates the
agent class with ``cls()``, so the tool layer cannot consume a
constructor-injected retriever in v0.1).
"""

from ajolopy import Module
from docsbot.agents.docs import DocsAgent


@Module(agents=[DocsAgent])
class AppModule:
    """Root module — one agent, one ``@Stream("/chat")`` endpoint."""


__all__ = ["AppModule"]
