"""Negative-path tests for GeminiProvider.

The router would normally prevent a non-Gemini model from ever reaching
this provider; these tests pin the defence-in-depth check inside the
provider so subclasses or direct callers cannot silently route the wrong
model.
"""

import pytest

from ajolopy.providers import Message
from ajolopy.providers.gemini import GeminiProvider, GeminiProviderError

from .conftest import make_async_client


@pytest.mark.asyncio
async def test_complete_rejects_non_gemini_model() -> None:
    provider = GeminiProvider(client=make_async_client())
    with pytest.raises(GeminiProviderError, match="gpt-4o-mini"):
        await provider.complete(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_stream_rejects_non_gemini_model() -> None:
    provider = GeminiProvider(client=make_async_client())
    with pytest.raises(GeminiProviderError, match="claude-sonnet-4-7"):
        # Build the iterator — the model check raises eagerly before any
        # generator is created.
        provider.stream(
            model="claude-sonnet-4-7",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_embed_rejects_non_gemini_model() -> None:
    provider = GeminiProvider(client=make_async_client())
    # An OpenAI embedding model is not a Gemini embedding model; the
    # embed-only allowlist rejects it.
    with pytest.raises(GeminiProviderError, match="claude"):
        await provider.embed(model="claude-sonnet-4-7", text="hi")
