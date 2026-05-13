"""Negative-path tests for OpenAIProvider.

The router would normally prevent a non-OpenAI model from ever reaching
this provider; this test pins the defence-in-depth check inside the
provider so subclasses or direct callers cannot silently route the wrong
model. The finish_reason fallback covers the legacy / safety values the
SDK can still emit but the framework's normalised literal does not know.
"""

import logging

import pytest

from ajolopy.providers import Message
from ajolopy.providers.openai import OpenAIProvider, OpenAIProviderError

from .conftest import make_async_client, make_chat_completion


@pytest.mark.asyncio
async def test_complete_rejects_non_openai_model() -> None:
    provider = OpenAIProvider(client=make_async_client())
    with pytest.raises(OpenAIProviderError, match="claude-sonnet-4-7"):
        await provider.complete(
            model="claude-sonnet-4-7",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_stream_rejects_non_openai_model() -> None:
    provider = OpenAIProvider(client=make_async_client())
    with pytest.raises(OpenAIProviderError, match="claude-sonnet-4-7"):
        # Build the iterator — the model check raises eagerly before any
        # generator is created.
        provider.stream(
            model="claude-sonnet-4-7",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_embed_rejects_non_openai_model() -> None:
    provider = OpenAIProvider(client=make_async_client())
    with pytest.raises(OpenAIProviderError, match="claude"):
        await provider.embed(model="claude-sonnet-4-7", text="hi")


@pytest.mark.parametrize("legacy_reason", ["function_call", "content_filter"])
@pytest.mark.asyncio
async def test_unknown_finish_reason_maps_to_stop_with_warning(
    caplog: pytest.LogCaptureFixture,
    legacy_reason: str,
) -> None:
    client = make_async_client(
        create_return=make_chat_completion(text="ok", finish_reason=legacy_reason)
    )
    provider = OpenAIProvider(client=client)
    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.openai"):
        response = await provider.complete(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )
    assert response.finish_reason == "stop"
    assert any(
        legacy_reason in record.message or legacy_reason in str(record.args)
        for record in caplog.records
    )
