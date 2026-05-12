"""Tests for AnthropicProvider construction and registry side effects.

Covers the "Construction & registration" acceptance group.
"""

from unittest.mock import MagicMock

import pytest

from ajolopy.providers import get_provider_class
from ajolopy.providers.anthropic import (
    AnthropicConfigError,
    AnthropicProvider,
)


def test_importing_package_registers_under_anthropic_key() -> None:
    # The conftest fixture has already imported the package; the registry
    # should resolve "anthropic" to AnthropicProvider.
    assert get_provider_class("anthropic") is AnthropicProvider


def test_explicit_api_key_constructs_internal_client() -> None:
    provider = AnthropicProvider(api_key="sk-ant-explicit")
    # The internal client is created lazily inside __init__; we just check
    # the property exposes something AsyncAnthropic-shaped.
    assert provider.client is not None
    assert hasattr(provider.client, "messages")


def test_supplied_client_is_used_verbatim() -> None:
    custom = MagicMock(name="custom AsyncAnthropic")
    provider = AnthropicProvider(client=custom)
    assert provider.client is custom


def test_env_var_fallback_constructs_client(with_anthropic_key: str) -> None:
    _ = with_anthropic_key
    provider = AnthropicProvider()
    assert provider.client is not None


def test_missing_env_var_raises_anthropic_config_error() -> None:
    with pytest.raises(AnthropicConfigError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()
