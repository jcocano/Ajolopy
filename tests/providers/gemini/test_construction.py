"""Tests for GeminiProvider construction and registry side effects.

Covers the "Construction & registration" acceptance group.
"""

from unittest.mock import MagicMock

import pytest

from ajolopy.providers import get_provider_class
from ajolopy.providers.gemini import (
    GeminiConfigError,
    GeminiProvider,
)


def test_importing_package_registers_under_gemini_key() -> None:
    # The conftest fixture has already imported the package; the registry
    # should resolve "gemini" to GeminiProvider.
    assert get_provider_class("gemini") is GeminiProvider


def test_explicit_api_key_constructs_internal_client() -> None:
    provider = GeminiProvider(api_key="AIza-explicit")
    # The internal client is created lazily inside __init__; we just check
    # the property exposes something genai.Client-shaped (has an `aio` attr).
    assert provider.client is not None
    assert hasattr(provider.client, "aio")


def test_supplied_client_is_used_verbatim() -> None:
    custom = MagicMock(name="custom genai.Client")
    provider = GeminiProvider(client=custom)
    assert provider.client is custom


def test_env_var_fallback_constructs_client(with_gemini_key: str) -> None:
    _ = with_gemini_key
    provider = GeminiProvider()
    assert provider.client is not None


def test_missing_env_var_raises_gemini_config_error() -> None:
    with pytest.raises(GeminiConfigError, match="GEMINI_API_KEY"):
        GeminiProvider()
