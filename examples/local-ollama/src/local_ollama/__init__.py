"""Local code reviewer powered by Ollama — the no-API-key Ajolopy example (AJ-66).

The package layout mirrors the AJ-50 ``support-agent`` and AJ-54
``docsbot`` examples one-to-one, with one strategic difference: the
agent's ``model`` string targets the **universal OpenAI-compatible
provider** instead of Anthropic. The framework's registry routes the
``ollama:`` prefix to :class:`UniversalOpenAIProvider`, which talks the
OpenAI wire format against a local Ollama server.

Modules:

- :mod:`local_ollama.agents.reviewer` — the ``CodeReviewer`` ``@Agent``
  with one ``@Tool`` (``lint_function``) and one ``@Stream("/chat")``.
- :mod:`local_ollama.app_module` — the root ``@Module`` wiring
  ``CodeReviewer`` into the DI container.
- :mod:`local_ollama.main` — the ASGI entry point used by
  ``ajolopy dev``.
"""

# Side-effect imports — register the provider classes under their
# routing keys so the agent's primary + fallback chain resolves at
# decoration time without ``ProviderNotRegisteredError``.
#
# - ``universal_openai`` covers the local Ollama primary (model
#   ``"ollama:llama3.3"``).
# - ``anthropic`` covers the cloud fallback (``"claude-haiku-4-5"``).
#   AJ-69 makes the fallback's provider *instance* lazy, but the
#   registry binding check stays eager — the import below satisfies
#   that check without validating ``ANTHROPIC_API_KEY``.
import ajolopy.providers.anthropic  # pyright: ignore[reportUnusedImport]
import ajolopy.providers.universal_openai  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
