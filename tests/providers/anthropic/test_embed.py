"""Tests for AnthropicProvider.embed().

Anthropic has no native embeddings endpoint; the method must raise a typed
error so callers can route through a real embeddings provider.
"""

import pytest

from ajolopy.providers.anthropic import (
    AnthropicEmbeddingsNotSupportedError,
    AnthropicProvider,
)

from .conftest import make_async_client


@pytest.mark.asyncio
async def test_embed_raises_typed_error() -> None:
    client = make_async_client()
    provider = AnthropicProvider(client=client)
    with pytest.raises(AnthropicEmbeddingsNotSupportedError, match="embeddings"):
        await provider.embed(model="claude-sonnet-4-7", text="hello")
