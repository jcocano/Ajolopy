"""Tests for resolve_provider / register_route.

Covers the "Routing" acceptance group. Every v0.1 provider family is exercised
with at least one representative model string.
"""

import pytest

from ajolopy.providers import UnknownModelError, register_route, resolve_provider


@pytest.mark.parametrize(
    ("model", "expected_key"),
    [
        ("claude-opus-4-7", "anthropic"),
        ("claude-haiku-4-5", "anthropic"),
        ("claude-opus-4-1", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("gpt-4-turbo", "openai"),
        ("o1-preview", "openai"),
        ("o1-mini", "openai"),
        ("o3-mini", "openai"),
        ("text-embedding-3-small", "openai"),
        ("gemini-2.5-pro", "gemini"),
        ("gemini-2.5-flash", "gemini"),
        ("ollama:llama3.3", "universal-openai"),
        ("groq:llama-3.3-70b", "universal-openai"),
        ("together:meta-llama/Llama-3.3-70B-Instruct", "universal-openai"),
        ("mistral:mistral-large-latest", "universal-openai"),
        ("deepseek:deepseek-chat", "universal-openai"),
        ("openrouter:anthropic/claude-3.5-sonnet", "universal-openai"),
        ("azure:my-deployment", "universal-openai"),
    ],
)
def test_default_route_table_covers_v0_1_providers(model: str, expected_key: str) -> None:
    assert resolve_provider(model) == expected_key


def test_unknown_model_string_raises_with_known_patterns() -> None:
    with pytest.raises(UnknownModelError) as info:
        resolve_provider("bogus-model-name")
    message = str(info.value)
    assert "bogus-model-name" in message
    # The error must hint at recognised prefix families so the user can self-correct.
    assert "claude-*" in message
    assert "gpt-*" in message


def test_register_route_adds_new_pattern() -> None:
    with pytest.raises(UnknownModelError):
        resolve_provider("plugin:something")
    register_route("plugin:*", "custom")
    assert resolve_provider("plugin:foo") == "custom"


def test_register_route_most_recent_wins_for_overlapping_patterns() -> None:
    register_route("claude-*", "custom-claude")
    assert resolve_provider("claude-opus-4-7") == "custom-claude"
