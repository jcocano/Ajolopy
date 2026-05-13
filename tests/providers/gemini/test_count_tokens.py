"""Tests for GeminiProvider.count_tokens().

When called outside a running event loop, the provider runs the SDK's
async ``count_tokens`` endpoint via ``asyncio.run``. On failure (or when
called from inside a running loop) it falls back to a deterministic
4-chars-per-token estimate and logs a warning. Matches AJ-19's pattern
verbatim.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ajolopy.providers.gemini import GeminiProvider

from .conftest import make_async_client


def test_count_tokens_uses_sdk_when_outside_event_loop() -> None:
    client = make_async_client(
        count_tokens_return=SimpleNamespace(total_tokens=42),
    )
    provider = GeminiProvider(client=client)
    assert provider.count_tokens(model="gemini-2.5-flash", text="hello") == 42


def test_count_tokens_falls_back_with_warning_on_sdk_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_async_client()
    client.aio.models.count_tokens = AsyncMock(side_effect=RuntimeError("SDK broken"))
    provider = GeminiProvider(client=client)
    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.gemini"):
        result = provider.count_tokens(model="gemini-2.5-flash", text="hello world")
    # "hello world" = 11 chars; 11 // 4 = 2, max(1, _) = 2.
    assert result == 2
    assert any("count_tokens failed" in record.getMessage() for record in caplog.records)


def test_count_tokens_falls_back_when_sdk_returns_no_total_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # If the SDK returns a response without a usable total_tokens int the
    # provider warns and falls back to the char estimate so callers never
    # get a misleading ``0``.
    client = make_async_client(
        count_tokens_return=SimpleNamespace(total_tokens=None),
    )
    provider = GeminiProvider(client=client)
    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.gemini"):
        result = provider.count_tokens(model="gemini-2.5-flash", text="hello world")
    assert result == 2
    assert any("no total_tokens" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_count_tokens_uses_estimate_inside_running_event_loop() -> None:
    # Inside an asyncio loop the sync helper cannot block on asyncio.run, so
    # it falls back to the char-based estimate without an SDK call.
    client = make_async_client(count_tokens_return=SimpleNamespace(total_tokens=99))
    provider = GeminiProvider(client=client)
    result = provider.count_tokens(model="gemini-2.5-flash", text="hello world")
    assert result == 2
    client.aio.models.count_tokens.assert_not_awaited()
