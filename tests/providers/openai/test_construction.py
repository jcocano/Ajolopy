"""Tests for OpenAIProvider construction and registry side effects.

Covers the "Construction & registration" acceptance group.
"""

from unittest.mock import MagicMock

import pytest

from ajolopy.providers import get_provider_class
from ajolopy.providers.openai import (
    OpenAIConfigError,
    OpenAIProvider,
)


def test_importing_package_registers_under_openai_key() -> None:
    # The conftest fixture has already imported the package; the registry
    # should resolve "openai" to OpenAIProvider.
    assert get_provider_class("openai") is OpenAIProvider


def test_explicit_api_key_constructs_internal_client() -> None:
    provider = OpenAIProvider(api_key="sk-explicit")
    # The internal client is created lazily inside __init__; we just check
    # the property exposes something AsyncOpenAI-shaped.
    assert provider.client is not None
    assert hasattr(provider.client, "chat")


def test_supplied_client_is_used_verbatim() -> None:
    custom = MagicMock(name="custom AsyncOpenAI")
    provider = OpenAIProvider(client=custom)
    assert provider.client is custom


def test_env_var_fallback_constructs_client(with_openai_key: str) -> None:
    _ = with_openai_key
    provider = OpenAIProvider()
    assert provider.client is not None


def test_missing_env_var_raises_openai_config_error() -> None:
    with pytest.raises(OpenAIConfigError, match="OPENAI_API_KEY"):
        OpenAIProvider()
