"""Root ``@Module`` for the on-call agent example.

Wires the ``OnCallAgent`` and its ``@Stream("/chat")`` endpoint into
the DI container. The ``Integrations``-style ``GitHubMCP`` class is
**not** listed here: ``@MCP``-decorated classes self-register into
the process-wide MCP registry at decoration time. Importing
:mod:`oncall_agent.agents.oncall` is enough to make the framework
drain the registry at boot.
"""

from ajolopy import Module
from oncall_agent.agents.oncall import OnCallAgent


@Module(agents=[OnCallAgent])
class AppModule:
    """Root module — one agent, one ``@Stream("/chat")`` endpoint."""


__all__ = ["AppModule"]
