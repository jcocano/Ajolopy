"""Runnable companion to the Ajolopy 3-step killer demo tutorial (AJ-50).

The package mirrors the tutorial layout one-to-one:

- :mod:`support_agent.agents.support` — Step 1's single ``Support`` agent.
- :mod:`support_agent.agents.team` — Step 3's ``Triage`` / ``Billing`` /
  ``Technical`` specialists, the ``Integrations`` ``@MCP`` block, and the
  ``SupportTeam`` ``@Workflow`` that ties them together.
- :mod:`support_agent.app_module` — the root ``@Module`` that wires
  whichever variant the ``SUPPORT_AGENT_MODE`` env var selects.
- :mod:`support_agent.main` — ASGI entry point used by ``ajolopy dev``.
"""

# Side-effect import — registers ``AnthropicProvider`` under the
# ``"anthropic"`` routing key so ``@Agent(model="claude-...")`` can
# resolve at decoration time without raising
# ``ProviderNotRegisteredError``. Mirrors the pattern documented in the
# framework's own provider-package docstrings. The class is bound to a
# name (rather than left as a bare side-effect import) so static
# analysers see it as a used symbol.
from ajolopy.providers.anthropic import AnthropicProvider as _AnthropicProvider

_PROVIDER_BOUND: type[_AnthropicProvider] = _AnthropicProvider

__all__ = ["__version__"]

__version__ = "0.0.1"
