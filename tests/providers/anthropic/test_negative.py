"""Negative-path tests for AnthropicProvider.

The router would normally prevent a non-Claude model from ever reaching this
provider; this test pins the defence-in-depth check inside the provider so
subclasses or direct callers cannot silently route the wrong model.
"""

import pytest

from ajolopy.providers import Message
from ajolopy.providers.anthropic import AnthropicProvider, AnthropicProviderError

from .conftest import make_async_client


@pytest.mark.asyncio
async def test_complete_rejects_non_claude_model() -> None:
    provider = AnthropicProvider(client=make_async_client())
    with pytest.raises(AnthropicProviderError, match="claude-"):
        await provider.complete(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_stream_rejects_non_claude_model() -> None:
    provider = AnthropicProvider(client=make_async_client())
    with pytest.raises(AnthropicProviderError, match="claude-"):
        # Build the iterator — the model check raises eagerly before any
        # generator is created.
        provider.stream(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )
