"""Google Gemini native provider.

Importing this package registers :class:`GeminiProvider` under the
``"gemini"`` key in the framework registry. From that moment on,
``@Agent(model="gemini-...")`` (and ``"text-embedding-..."`` /
``"embedding-..."`` for Gemini-native embedding models) resolves to this
implementation.

Side effect on import is intentional: it lets users opt-in to a provider
by simply importing its package, matching the pattern used by other
Python AI frameworks. To avoid the side effect, import only
``GeminiProvider`` and register manually.
"""

import contextlib

from ajolopy.providers.registry import register_provider

from .errors import GeminiConfigError, GeminiProviderError
from .provider import GeminiProvider

# Idempotent: re-registration is rejected by the registry unless overwrite=True.
# Suppress the duplicate-registration error so importing the package twice
# (e.g. from two test files in the same process) is a no-op for the caller.
with contextlib.suppress(ValueError):
    register_provider("gemini", GeminiProvider)


__all__ = [
    "GeminiConfigError",
    "GeminiProvider",
    "GeminiProviderError",
]
