"""Tests for OpenAIProvider.embed().

Covers the "embed()" acceptance group: single string input, batch input,
empty input short-circuit, and SDK-error wrapping.
"""

import httpx
import openai
import pytest

from ajolopy.providers.openai import OpenAIProvider, OpenAIProviderError

from .conftest import make_async_client, make_embeddings_response


@pytest.mark.asyncio
async def test_embed_single_string_returns_one_vector() -> None:
    client = make_async_client(embed_return=make_embeddings_response([[0.1, 0.2, 0.3]]))
    provider = OpenAIProvider(client=client)
    vectors = await provider.embed(model="text-embedding-3-small", text="hello")
    assert vectors == [[0.1, 0.2, 0.3]]
    client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-small",
        input=["hello"],
    )


@pytest.mark.asyncio
async def test_embed_batch_returns_vectors_in_input_order() -> None:
    client = make_async_client(embed_return=make_embeddings_response([[0.1, 0.2], [0.3, 0.4]]))
    provider = OpenAIProvider(client=client)
    vectors = await provider.embed(model="text-embedding-3-small", text=["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    kwargs = client.embeddings.create.call_args.kwargs
    assert kwargs["input"] == ["a", "b"]


@pytest.mark.asyncio
async def test_embed_empty_list_short_circuits_without_sdk_call() -> None:
    client = make_async_client()
    provider = OpenAIProvider(client=client)
    vectors = await provider.embed(model="text-embedding-3-small", text=[])
    assert vectors == []
    client.embeddings.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_embed_retriable_sdk_error_surfaces_as_provider_error() -> None:
    request = httpx.Request("POST", "https://example.invalid")
    client = make_async_client(embed_side_effect=openai.APIConnectionError(request=request))
    provider = OpenAIProvider(client=client)
    with pytest.raises(OpenAIProviderError, match="OpenAI SDK error"):
        await provider.embed(model="text-embedding-3-small", text="hello")
