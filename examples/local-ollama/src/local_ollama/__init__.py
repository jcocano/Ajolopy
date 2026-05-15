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

# Side-effect import — registers ``UniversalOpenAIProvider`` under the
# ``"universal-openai"`` routing key so ``@Agent(model="ollama:...")``
# can resolve at decoration time without raising
# ``ProviderNotRegisteredError``. See
# ``ajolopy/providers/universal_openai/__init__.py``.
import ajolopy.providers.universal_openai  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
