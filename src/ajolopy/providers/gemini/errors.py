"""Errors raised by ``GeminiProvider``.

All provider-specific errors derive from ``GeminiProviderError`` so callers
can catch the family with a single ``except``. The base class inherits from
``LLMProviderError`` so framework-level catch-blocks (`@Agent` retry,
fallback orchestration) can treat any provider's failure uniformly.
Configuration problems have a dedicated subclass because the framework
bootstrap (AJ-14) wants to surface them at startup rather than at first
request.

The AJ-58 cache-lifecycle errors form their own ``GeminiCacheError``
subtree so callers opting into Context Caching can catch the cache-only
failures without swallowing unrelated provider errors.
"""

from ajolopy.providers.base import LLMProviderError


class GeminiProviderError(LLMProviderError):
    """Base class for any error raised inside ``GeminiProvider``."""


class GeminiConfigError(GeminiProviderError):
    """The provider could not be constructed (e.g. missing ``GEMINI_API_KEY``)."""


class GeminiCacheError(GeminiProviderError):
    """Base class for AJ-58 cache-lifecycle errors.

    Catch this to react to any cache-related failure (minimum-tokens
    rejection, expiry surfaced when the policy says ``"error"``, SDK
    rejection on ``caches.create``) without swallowing unrelated
    ``GeminiProviderError`` failures.
    """


class GeminiCacheMinTokensError(GeminiCacheError):
    """``complete()/stream()`` was called with ``cache=True`` but the
    derived prefix sits below the configured ``cache_min_tokens``.

    Raised *before* any ``caches.create`` SDK call so callers see a
    typed framework error instead of letting the provider waste a
    server-side resource on too-small content. The error message names
    the actual token count, the threshold, and the constructor kwarg to
    override.
    """


class GeminiCacheExpiredError(GeminiCacheError):
    """A cached-content reference returned a 404 from the SDK.

    Raised when ``cache_on_expired="error"`` and the second call refers
    to a TTL-expired cache, or unconditionally on ``stream()`` (the
    streaming path cannot replay already-yielded deltas after a
    transparent recreate, so the iterator surfaces this error regardless
    of the kwarg). The error message points callers to retry as a fresh
    call.
    """


class GeminiCacheCreateError(GeminiCacheError):
    """``client.aio.caches.create(...)`` rejected the request.

    Raised when the initial create call fails, or when the recreate path
    triggered by ``cache_on_expired="recreate"`` fails again. Wraps the
    underlying SDK exception via ``__cause__`` so callers can inspect the
    transport-level reason.
    """
