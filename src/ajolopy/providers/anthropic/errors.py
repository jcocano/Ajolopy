"""Errors raised by ``AnthropicProvider``.

All provider-specific errors derive from ``AnthropicProviderError`` so
callers can catch the family with a single ``except``. The base class in
turn inherits from ``LLMProviderError`` so framework-level catch-blocks
(`@Agent` retry, fallback orchestration) can treat any provider's failure
uniformly. Configuration problems and the embeddings-unsupported case
have dedicated subclasses because they need distinct handling.
"""

from ajolopy.providers.base import LLMProviderError


class AnthropicProviderError(LLMProviderError):
    """Base class for any error raised inside ``AnthropicProvider``."""


class AnthropicConfigError(AnthropicProviderError):
    """The provider could not be constructed (e.g. missing ``ANTHROPIC_API_KEY``)."""


class AnthropicEmbeddingsNotSupportedError(AnthropicProviderError):
    """Anthropic does not ship a native embeddings endpoint."""
