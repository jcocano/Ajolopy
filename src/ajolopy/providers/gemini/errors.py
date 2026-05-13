"""Errors raised by ``GeminiProvider``.

All provider-specific errors derive from ``GeminiProviderError`` so callers
can catch the family with a single ``except``. The base class inherits from
``LLMProviderError`` so framework-level catch-blocks (`@Agent` retry,
fallback orchestration) can treat any provider's failure uniformly.
Configuration problems have a dedicated subclass because the framework
bootstrap (AJ-14) wants to surface them at startup rather than at first
request.
"""

from ajolopy.providers.base import LLMProviderError


class GeminiProviderError(LLMProviderError):
    """Base class for any error raised inside ``GeminiProvider``."""


class GeminiConfigError(GeminiProviderError):
    """The provider could not be constructed (e.g. missing ``GEMINI_API_KEY``)."""
