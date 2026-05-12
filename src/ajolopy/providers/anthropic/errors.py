"""Errors raised by ``AnthropicProvider``.

All provider-specific errors derive from ``AnthropicProviderError`` so
callers can catch the family with a single ``except``. Configuration
problems and the embeddings-unsupported case have dedicated subclasses
because they require different handling (the former is a bootstrap fault,
the latter a routing-time decision).
"""


class AnthropicProviderError(RuntimeError):
    """Base class for any error raised inside ``AnthropicProvider``."""


class AnthropicConfigError(AnthropicProviderError):
    """The provider could not be constructed (e.g. missing ``ANTHROPIC_API_KEY``)."""


class AnthropicEmbeddingsNotSupportedError(AnthropicProviderError):
    """Anthropic does not ship a native embeddings endpoint."""
