"""Capability-flag tests for OpenAIProvider."""

from ajolopy.providers.openai import OpenAIProvider

from .conftest import make_async_client


def test_supports_prompt_caching_is_true() -> None:
    provider = OpenAIProvider(client=make_async_client())
    # OpenAI caches automatically; the framework still reports the
    # capability so callers can rely on the feature.
    assert provider.supports_prompt_caching() is True


def test_supports_tool_calling_is_true() -> None:
    provider = OpenAIProvider(client=make_async_client())
    assert provider.supports_tool_calling() is True
