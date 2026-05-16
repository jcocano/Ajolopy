"""Negative-path tests for UniversalOpenAIProvider.

The router would normally only feed prefixed model strings to this
provider; the checks below pin defence-in-depth behaviour so that
subclasses or direct callers cannot silently route the wrong model.
The finish_reason mapping is exercised here too, going through the
shared helper that AJ-20 also depends on.
"""

import logging

import pytest

from ajolopy.providers import Message
from ajolopy.providers.universal_openai import (
    UniversalOpenAIProvider,
    UniversalProviderError,
)

from .conftest import make_async_client, make_chat_completion


@pytest.mark.asyncio
async def test_bare_openai_model_raises_universal_provider_error() -> None:
    # An unprefixed OpenAI model never belongs to the universal
    # provider; it must raise so the registry misconfiguration is loud.
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderError, match="Supported prefixes"):
        await provider.complete(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_bare_anthropic_model_raises_universal_provider_error() -> None:
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderError, match="Supported prefixes"):
        await provider.complete(
            model="claude-opus-4-7",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_azure_prefix_raises_pointing_at_deferred_item() -> None:
    # azure:* has a route entry in _DEFAULT_ROUTES so the resolver
    # doesn't crash, but actually serving Azure needs AsyncAzureOpenAI
    # plus deployment routing — deferred to a future item.
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderError, match="Azure OpenAI"):
        await provider.complete(
            model="azure:gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_unknown_prefix_raises_with_supported_list() -> None:
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderError) as exc_info:
        await provider.complete(
            model="vllm:my-model",
            messages=[Message(role="user", content="hi")],
        )
    # The error names the prefix and lists the known options.
    msg = str(exc_info.value)
    assert "vllm" in msg
    assert "groq" in msg


@pytest.mark.parametrize("legacy_reason", ["function_call", "content_filter"])
@pytest.mark.asyncio
async def test_unknown_finish_reason_maps_to_stop_with_warning(
    caplog: pytest.LogCaptureFixture,
    legacy_reason: str,
) -> None:
    client = make_async_client(
        create_return=make_chat_completion(text="ok", finish_reason=legacy_reason)
    )
    provider = UniversalOpenAIProvider(clients={"groq": client})
    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.universal_openai"):
        response = await provider.complete(
            model="groq:llama-3.3-70b-versatile",
            messages=[Message(role="user", content="hi")],
        )
    assert response.finish_reason == "stop"
    assert any(
        legacy_reason in record.message or legacy_reason in str(record.args)
        for record in caplog.records
    )
