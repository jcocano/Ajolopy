"""Tests for UniversalOpenAIProvider.count_tokens().

Universal token counting uses the gpt-4o tokenizer as a generic default
(Llama/Mixtral/DeepSeek tokenizers diverge but tiktoken is the only
offline option that ships pre-built wheels). A one-time warning fires
per prefix on first use; subsequent calls stay silent.
"""

import logging

import pytest

from ajolopy.providers.universal_openai import (
    UniversalOpenAIProvider,
    UniversalProviderError,
)


def test_count_tokens_returns_positive_int_for_known_prefix() -> None:
    provider = UniversalOpenAIProvider()
    count = provider.count_tokens(model="groq:llama-3.3-70b-versatile", text="hello")
    assert isinstance(count, int)
    assert count >= 1


def test_count_tokens_logs_one_time_warning_per_prefix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Per spec: the warning is per-prefix and emitted exactly once on
    # first use, so hot paths do not flood logs.
    provider = UniversalOpenAIProvider()
    # The module logger uses __name__ which resolves to
    # ``ajolopy.providers.universal_openai.provider`` for the submodule;
    # capture from the parent so any descendant emits.
    logger_name = "ajolopy.providers.universal_openai"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        provider.count_tokens(model="groq:llama-3.3-70b-versatile", text="x")
        provider.count_tokens(model="groq:llama-3.3-70b-versatile", text="y")
    warnings_for_groq = [
        r for r in caplog.records if r.name.startswith(logger_name) and "'groq'" in r.message
    ]
    # The warning fires once even though two calls were made.
    assert len(warnings_for_groq) == 1


def test_count_tokens_warns_separately_per_prefix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Two different prefixes get one warning each — the gate is
    # per-prefix, not global.
    provider = UniversalOpenAIProvider()
    logger_name = "ajolopy.providers.universal_openai"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        provider.count_tokens(model="groq:llama", text="x")
        provider.count_tokens(model="together:something", text="x")
    prefixes_warned = {
        prefix
        for prefix in ("groq", "together")
        if any(repr(prefix) in r.message for r in caplog.records if r.name.startswith(logger_name))
    }
    assert prefixes_warned == {"groq", "together"}


def test_count_tokens_raises_for_unknown_prefix() -> None:
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderError, match="Unsupported universal prefix"):
        provider.count_tokens(model="vllm:my-model", text="hi")


def test_count_tokens_raises_for_bare_model_string() -> None:
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderError, match="prefixed model"):
        provider.count_tokens(model="gpt-4o-mini", text="hi")
