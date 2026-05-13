"""OpenAI native provider.

Importing this package registers :class:`OpenAIProvider` under the
``"openai"`` key in the framework registry. From that moment on,
``@Agent(model="gpt-...")`` (and ``"o1-..."``, ``"o3-..."``,
``"text-embedding-3*"``) resolves to this implementation.

Side effect on import is intentional: it lets users opt-in to a provider by
simply importing its package, matching the pattern used by other Python AI
frameworks. To avoid the side effect, import only ``OpenAIProvider`` and
register manually.
"""

import contextlib

from ajolopy.providers.registry import register_provider

from .errors import OpenAIConfigError, OpenAIProviderError
from .provider import OpenAIProvider

# Idempotent: re-registration is rejected by the registry unless overwrite=True.
# Suppress the duplicate-registration error so importing the package twice
# (e.g. from two test files in the same process) is a no-op for the caller.
with contextlib.suppress(ValueError):
    register_provider("openai", OpenAIProvider)


__all__ = [
    "OpenAIConfigError",
    "OpenAIProvider",
    "OpenAIProviderError",
]
