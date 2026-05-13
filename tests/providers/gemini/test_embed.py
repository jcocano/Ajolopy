"""Tests for GeminiProvider.embed().

Covers the "embed()" acceptance group: single string input, batch input,
empty input short-circuit, defence-in-depth rejection of non-embedding
models, and SDK-error wrapping.
"""

import pytest
from google.genai import errors as genai_errors

from ajolopy.providers.gemini import GeminiProvider, GeminiProviderError

from .conftest import make_async_client, make_embeddings_response


@pytest.mark.asyncio
async def test_embed_single_string_returns_one_vector() -> None:
    client = make_async_client(embed_return=make_embeddings_response([[0.1, 0.2, 0.3]]))
    provider = GeminiProvider(client=client)
    vectors = await provider.embed(model="text-embedding-004", text="hello")
    assert vectors == [[0.1, 0.2, 0.3]]
    client.aio.models.embed_content.assert_awaited_once_with(
        model="text-embedding-004",
        contents=["hello"],
    )


@pytest.mark.asyncio
async def test_embed_batch_returns_vectors_in_input_order() -> None:
    client = make_async_client(embed_return=make_embeddings_response([[0.1, 0.2], [0.3, 0.4]]))
    provider = GeminiProvider(client=client)
    vectors = await provider.embed(model="text-embedding-004", text=["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    kwargs = client.aio.models.embed_content.call_args.kwargs
    assert kwargs["contents"] == ["a", "b"]


@pytest.mark.asyncio
async def test_embed_empty_list_short_circuits_without_sdk_call() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    vectors = await provider.embed(model="text-embedding-004", text=[])
    assert vectors == []
    client.aio.models.embed_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_embed_rejects_generation_model() -> None:
    # Defence-in-depth: passing a generation model to embed() is a common
    # copy-paste mistake; surface a typed framework error instead of
    # letting the SDK fail with a generic 400.
    client = make_async_client()
    provider = GeminiProvider(client=client)
    with pytest.raises(GeminiProviderError, match=r"gemini-2\.5-flash"):
        await provider.embed(model="gemini-2.5-flash", text="hello")
    client.aio.models.embed_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_embed_retriable_sdk_error_surfaces_as_provider_error() -> None:
    sdk_exc = genai_errors.APIError(code=500, response_json={"error": {"message": "boom"}})
    client = make_async_client(embed_side_effect=sdk_exc)
    provider = GeminiProvider(client=client)
    with pytest.raises(GeminiProviderError, match="Gemini SDK error"):
        await provider.embed(model="text-embedding-004", text="hello")
