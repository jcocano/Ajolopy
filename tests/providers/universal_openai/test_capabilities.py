"""Capability-flag tests for UniversalOpenAIProvider."""

from ajolopy.providers.universal_openai import UniversalOpenAIProvider


def test_supports_prompt_caching_is_false() -> None:
    # None of the universal providers expose an opt-in caching flag;
    # the framework reports False so callers do not rely on the feature.
    provider = UniversalOpenAIProvider()
    assert provider.supports_prompt_caching() is False


def test_supports_tool_calling_is_true() -> None:
    # Every modern OpenAI-compatible API supports function calling on
    # the wire format; per-model availability is the caller's concern.
    provider = UniversalOpenAIProvider()
    assert provider.supports_tool_calling() is True
