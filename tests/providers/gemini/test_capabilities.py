"""Capability-flag tests for GeminiProvider."""

from ajolopy.providers.gemini import GeminiProvider

from .conftest import make_async_client


def test_supports_prompt_caching_is_false_by_default() -> None:
    # Default construction matches AJ-21's release — caching is off until
    # the caller explicitly flips ``cache_strategy="auto"`` (AJ-58).
    provider = GeminiProvider(client=make_async_client())
    assert provider.supports_prompt_caching() is False


def test_supports_prompt_caching_flips_true_when_strategy_is_auto() -> None:
    # AJ-58: opting into the cache lifecycle flips the capability flag so
    # the framework can introspect whether passing ``cache=True`` on the
    # wire is meaningful.
    provider = GeminiProvider(client=make_async_client(), cache_strategy="auto")
    assert provider.supports_prompt_caching() is True


def test_supports_tool_calling_is_true() -> None:
    provider = GeminiProvider(client=make_async_client())
    assert provider.supports_tool_calling() is True
