"""Errors raised by ``UniversalOpenAIProvider``.

All provider-specific errors derive from ``UniversalProviderError`` so
callers can catch the family with a single ``except``. The base class
inherits from ``LLMProviderError`` so framework-level catch-blocks
(`@Agent` retry, fallback orchestration) can treat any provider's
failure uniformly. Configuration problems and the
embeddings-unsupported case have dedicated subclasses because they
need distinct handling — bootstrap surfaces config errors at startup,
and embedding callers expect a typed signal pointing at OpenAI's
``text-embedding-3-*`` as the documented fallback.
"""

from ajolopy.providers.base import LLMProviderError


class UniversalProviderError(LLMProviderError):
    """Base class for any error raised inside ``UniversalOpenAIProvider``."""


class UniversalProviderConfigError(UniversalProviderError):
    """The provider could not resolve a client for a prefix.

    Raised lazily on the first request that targets a prefix whose
    API-key env var is missing (e.g. ``GROQ_API_KEY``). The framework
    bootstrap (AJ-14) is expected to forward keys explicitly via the
    ``api_keys=`` kwarg; this error exists for the standalone-script
    path and as a safety net.
    """


class UniversalEmbeddingsNotSupportedError(UniversalProviderError):
    """The targeted prefix does not expose an embeddings endpoint.

    ``groq``, ``deepseek``, and ``openrouter`` do not ship a native
    embeddings API. Callers should route embeddings to OpenAI's
    ``text-embedding-3-*`` models instead — the message points there
    explicitly so framework users learn the documented fallback path.
    """
