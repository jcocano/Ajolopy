"""Runnable Ajolopy example: on-call agent via ``@MCP`` (AJ-63).

The package shows how to consume a real, external Model Context
Protocol server (the canonical
``@modelcontextprotocol/server-github`` published by the MCP project)
from inside an Ajolopy ``@Agent``:

- :mod:`oncall_agent.integrations` — the ``@MCP`` block declaring the
  GitHub server, its stdio transport, and the ``${GITHUB_TOKEN}``
  auth substitution.
- :mod:`oncall_agent.agents.oncall` — the ``OnCallAgent`` ``@Agent``
  with one local ``@Tool`` (``summarize_request``), a
  ``@Stream("/chat")`` endpoint, and ``integrations=[GitHubMCP]``.
- :mod:`oncall_agent.app_module` — the root ``@Module`` wiring the
  agent into the DI container.
- :mod:`oncall_agent.main` — the ASGI entry point used by
  ``ajolopy dev``.
"""

# Side-effect import — registers ``AnthropicProvider`` under the
# ``"anthropic"`` routing key so ``@Agent(model="claude-...")`` can
# resolve at decoration time without raising
# ``ProviderNotRegisteredError``. See
# ``ajolopy/providers/anthropic/__init__.py``.
import ajolopy.providers.anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
