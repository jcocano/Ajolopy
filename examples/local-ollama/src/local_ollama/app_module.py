"""Root ``@Module`` for the local-ollama example.

The module declares :class:`~local_ollama.agents.reviewer.CodeReviewer`
as the sole agent. No external service singletons, no MCP block — the
demo is deliberately the smallest possible runnable surface to keep the
no-API-key onboarding under five commands.
"""

from ajolopy import Module
from local_ollama.agents.reviewer import CodeReviewer


@Module(agents=[CodeReviewer])
class AppModule:
    """Root module — one agent, one ``@Stream("/chat")`` endpoint."""


__all__ = ["AppModule"]
