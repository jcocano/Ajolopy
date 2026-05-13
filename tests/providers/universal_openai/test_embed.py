"""Tests for UniversalOpenAIProvider.embed().

Covers the "embed()" acceptance group: prefix stripping, single + batch
inputs, the typed UniversalEmbeddingsNotSupportedError for prefixes
whose capability table says ``supports_embed=False``.
"""

import pytest

from ajolopy.providers.universal_openai import (
    UniversalEmbeddingsNotSupportedError,
    UniversalOpenAIProvider,
)

from .conftest import make_async_client, make_embeddings_response


@pytest.mark.asyncio
async def test_embed_single_string_strips_prefix_and_returns_one_vector() -> None:
    client = make_async_client(embed_return=make_embeddings_response([[0.1, 0.2, 0.3]]))
    provider = UniversalOpenAIProvider(clients={"ollama": client})
    vectors = await provider.embed(model="ollama:nomic-embed-text", text="hi")
    assert vectors == [[0.1, 0.2, 0.3]]
    client.embeddings.create.assert_awaited_once_with(
        model="nomic-embed-text",
        input=["hi"],
    )


@pytest.mark.asyncio
async def test_embed_batch_returns_vectors_in_input_order() -> None:
    client = make_async_client(embed_return=make_embeddings_response([[0.1, 0.2], [0.3, 0.4]]))
    provider = UniversalOpenAIProvider(clients={"together": client})
    vectors = await provider.embed(
        model="together:togethercomputer/m2-bert-80M-8k-retrieval",
        text=["a", "b"],
    )
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    kwargs = client.embeddings.create.call_args.kwargs
    assert kwargs["input"] == ["a", "b"]
    # The prefix was stripped before the SDK call.
    assert kwargs["model"] == "togethercomputer/m2-bert-80M-8k-retrieval"


@pytest.mark.asyncio
async def test_embed_empty_list_short_circuits_without_sdk_call() -> None:
    client = make_async_client()
    provider = UniversalOpenAIProvider(clients={"ollama": client})
    vectors = await provider.embed(model="ollama:nomic-embed-text", text=[])
    assert vectors == []
    client.embeddings.create.assert_not_awaited()


# Spec capability table: only these prefixes do NOT expose embeddings.
_NO_EMBED_PREFIXES = ("groq", "deepseek", "openrouter")


@pytest.mark.parametrize("prefix", _NO_EMBED_PREFIXES)
@pytest.mark.asyncio
async def test_embed_raises_typed_error_for_prefixes_without_embeddings(
    prefix: str,
) -> None:
    # The error must surface BEFORE the SDK is consulted, since these
    # providers genuinely lack an embeddings endpoint. The message
    # points callers at OpenAI's text-embedding-3-* fallback so they
    # know which model to route through instead.
    client = make_async_client()
    provider = UniversalOpenAIProvider(clients={prefix: client})
    with pytest.raises(UniversalEmbeddingsNotSupportedError) as exc_info:
        await provider.embed(model=f"{prefix}:anything", text="x")
    msg = str(exc_info.value)
    assert "text-embedding-3" in msg
    # The SDK must never have been called — the failure is local.
    client.embeddings.create.assert_not_awaited()


@pytest.mark.parametrize("prefix", ["ollama", "together", "mistral"])
@pytest.mark.asyncio
async def test_embed_passes_through_for_prefixes_with_native_support(
    prefix: str,
) -> None:
    # Parametrised positive coverage to balance the negative parametric.
    client = make_async_client(embed_return=make_embeddings_response([[1.0, 2.0]]))
    provider = UniversalOpenAIProvider(clients={prefix: client})
    vectors = await provider.embed(model=f"{prefix}:some-embed-model", text="x")
    assert vectors == [[1.0, 2.0]]
    client.embeddings.create.assert_awaited_once()
