"""Capability-flag tests for GeminiProvider."""

from ajolopy.providers.gemini import GeminiProvider

from .conftest import make_async_client


def test_supports_prompt_caching_is_false() -> None:
    # Gemini's prompt caching requires an explicit cachedContent lifecycle
    # that does not fit the stateless `cache: bool` flag. Honestly advertise
    # False here; the full lifecycle lives in AJ-58.
    provider = GeminiProvider(client=make_async_client())
    assert provider.supports_prompt_caching() is False


def test_supports_tool_calling_is_true() -> None:
    provider = GeminiProvider(client=make_async_client())
    assert provider.supports_tool_calling() is True
