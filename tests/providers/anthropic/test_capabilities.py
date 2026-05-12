"""Capability-flag tests for AnthropicProvider."""

from ajolopy.providers.anthropic import AnthropicProvider

from .conftest import make_async_client


def test_supports_prompt_caching_is_true() -> None:
    provider = AnthropicProvider(client=make_async_client())
    assert provider.supports_prompt_caching() is True


def test_supports_tool_calling_is_true() -> None:
    provider = AnthropicProvider(client=make_async_client())
    assert provider.supports_tool_calling() is True
