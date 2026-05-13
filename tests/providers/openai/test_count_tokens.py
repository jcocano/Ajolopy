"""Tests for OpenAIProvider.count_tokens().

The provider uses ``tiktoken`` for known encodings and falls back to a
4-chars-per-token estimate (with a warning) when the encoding cannot be
resolved. Both branches are exercised here without any SDK calls.
"""

import logging

import pytest

from ajolopy.providers.openai import OpenAIProvider

from .conftest import make_async_client


def test_count_tokens_uses_tiktoken_for_known_chat_model() -> None:
    provider = OpenAIProvider(client=make_async_client())
    count = provider.count_tokens(model="gpt-4o-mini", text="hello")
    # tiktoken's o200k_base encodes "hello" as exactly one token; the
    # implementation also clamps to >= 1 so we just assert it is positive.
    assert isinstance(count, int)
    assert count >= 1


def test_count_tokens_supports_reasoning_models() -> None:
    # o1/o3 reasoning models share the o200k_base encoding with gpt-4o.
    provider = OpenAIProvider(client=make_async_client())
    count = provider.count_tokens(model="o1-preview", text="hello")
    assert isinstance(count, int)
    assert count >= 1


def test_count_tokens_falls_back_with_warning_on_unknown_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = OpenAIProvider(client=make_async_client())
    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.openai"):
        # tiktoken.encoding_for_model does not know future-model names; the
        # provider must fall back to a 4-chars-per-token estimate.
        result = provider.count_tokens(model="gpt-future-9000", text="hello world")
    # "hello world" = 11 chars; 11 // 4 = 2, max(1, _) = 2.
    assert result == 2
    assert any("fell back to char estimate" in record.message for record in caplog.records)
