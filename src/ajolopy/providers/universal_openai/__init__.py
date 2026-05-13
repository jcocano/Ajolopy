"""Universal OpenAI-compatible provider.

Importing this package registers :class:`UniversalOpenAIProvider` under
the ``"universal-openai"`` key in the framework registry. From that
moment on, every prefixed model string the registry already routes to
``"universal-openai"`` — ``ollama:*``, ``groq:*``, ``together:*``,
``mistral:*``, ``deepseek:*``, ``openrouter:*`` — resolves to this
implementation.

Side effect on import is intentional: it lets users opt-in to the
provider by simply importing its package, matching the pattern used by
the other v0.1 providers (AJ-19 / AJ-20). To avoid the side effect,
import only :class:`UniversalOpenAIProvider` and register manually.
"""

import contextlib

from ajolopy.providers.registry import register_provider

from .errors import (
    UniversalEmbeddingsNotSupportedError,
    UniversalProviderConfigError,
    UniversalProviderError,
)
from .provider import UniversalOpenAIProvider

# Idempotent: re-registration is rejected by the registry unless
# overwrite=True. Suppress the duplicate-registration error so importing
# the package twice (e.g. from two test files in the same process) is a
# no-op for the caller.
with contextlib.suppress(ValueError):
    register_provider("universal-openai", UniversalOpenAIProvider)


__all__ = [
    "UniversalEmbeddingsNotSupportedError",
    "UniversalOpenAIProvider",
    "UniversalProviderConfigError",
    "UniversalProviderError",
]
