"""Shared fixtures for ``ajolopy.rag`` tests.

The retrievers ask the provider layer for embeddings. The top-level
``isolate_registry`` autouse fixture wipes the registry between tests,
so every retriever test that calls ``index`` / ``query`` first needs a
fake embedding provider registered under the right routing prefix.

``fake_embedding_provider`` registers a deterministic
:class:`LLMProvider` (text → fixed-length unit vector) under the
``openai`` key + ``text-embedding-3-*`` route, mirroring the default
routing in :mod:`ajolopy.providers.registry`. Tests can call
``ajolopy.rag.QdrantRetriever(..., embedding_model="text-embedding-3-small")``
without touching the network.
"""

from collections.abc import AsyncIterator
from typing import override

import pytest

from ajolopy.providers import (
    Chunk,
    LLMProvider,
    Message,
    Response,
    Tool,
    register_provider,
)


class _DeterministicEmbeddingProvider(LLMProvider):
    """A toy embedding provider for retriever tests.

    Produces a fixed-length unit vector per input text that is uniquely
    determined by the text content. Two distinct strings get distinct
    vectors; the same string always gets the same vector. Enough to
    drive cosine-similarity queries deterministically without any
    network I/O.
    """

    GEN_AI_SYSTEM = "fake_embeddings"

    def __init__(self, dim: int = 1536) -> None:
        self._dim = dim
        self.embed_calls: list[tuple[str, list[str]]] = []

    def _vector_for(self, text: str) -> list[float]:
        # Build a sparse one-hot-style vector seeded by the text's hash
        # so cosine similarity discriminates between distinct inputs.
        seed = hash(text) & 0xFFFFFFFF
        index = seed % self._dim
        vector = [0.0] * self._dim
        vector[index] = 1.0
        # Spread some weight to a second slot so close-but-not-equal
        # strings still produce comparable scores instead of 0.0.
        secondary = (seed >> 8) % self._dim
        if secondary != index:
            vector[secondary] = 0.5
        # Normalise to unit length so cosine similarity collapses to a
        # plain dot product on the consumer side.
        norm = sum(v * v for v in vector) ** 0.5
        return [v / norm for v in vector]

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        raise NotImplementedError("Embedding-only fake provider.")

    @override
    def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:
        raise NotImplementedError("Embedding-only fake provider.")

    @override
    async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
        inputs = [text] if isinstance(text, str) else list(text)
        self.embed_calls.append((model, list(inputs)))
        return [self._vector_for(t) for t in inputs]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        return max(1, len(text.split()))

    @override
    def supports_prompt_caching(self) -> bool:
        return False

    @override
    def supports_tool_calling(self) -> bool:
        return False


@pytest.fixture
def fake_embedding_provider() -> type[_DeterministicEmbeddingProvider]:
    """Register the deterministic embedding provider under ``openai``.

    Returns the class so tests that want to peek at ``embed_calls``
    can instantiate their own copy after grabbing the registered class
    via :func:`ajolopy.providers.get_provider_class`.
    """
    register_provider("openai", _DeterministicEmbeddingProvider)
    return _DeterministicEmbeddingProvider
