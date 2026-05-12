"""Tests for AnthropicProvider.count_tokens().

When called outside of a running event loop, the provider attempts the SDK's
async count_tokens endpoint synchronously via asyncio.run. On failure (or
when called from inside a running loop) it falls back to a deterministic
4-chars-per-token estimate and logs a warning.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ajolopy.providers.anthropic import AnthropicProvider

from .conftest import make_async_client


def test_count_tokens_uses_sdk_when_outside_event_loop() -> None:
    client = make_async_client()
    # Wire a successful count_tokens mock that returns input_tokens=42.
    client.messages.count_tokens = AsyncMock(return_value=SimpleNamespace(input_tokens=42))
    provider = AnthropicProvider(client=client)
    assert provider.count_tokens(model="claude-sonnet-4-7", text="hello") == 42


def test_count_tokens_falls_back_with_warning_on_sdk_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_async_client()
    client.messages.count_tokens = AsyncMock(side_effect=RuntimeError("SDK broken"))
    provider = AnthropicProvider(client=client)
    with caplog.at_level(logging.WARNING):
        result = provider.count_tokens(model="claude-sonnet-4-7", text="hello world")
    # "hello world" = 11 chars; ~11/4 = 2 with int division, max(1, _) = 2.
    assert result == 2
    assert any("count_tokens failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_count_tokens_uses_estimate_inside_running_event_loop() -> None:
    # Inside an asyncio loop the sync helper cannot block on asyncio.run, so
    # it falls back to the char-based estimate without an SDK call.
    client = make_async_client()
    client.messages.count_tokens = AsyncMock(return_value=SimpleNamespace(input_tokens=99))
    provider = AnthropicProvider(client=client)
    result = provider.count_tokens(model="claude-sonnet-4-7", text="hello world")
    assert result == 2
    client.messages.count_tokens.assert_not_awaited()
