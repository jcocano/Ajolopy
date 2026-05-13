"""Shared fixtures and helpers for GeminiProvider tests.

The tests *never* hit the network — every interaction with the
``google-genai`` SDK goes through ``AsyncMock`` shims set up here.
``GEMINI_API_KEY`` is cleared per-test so the provider's env-var
fallback branch is reachable deterministically; opt back in with
``with_gemini_key``.
"""

import contextlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ajolopy.providers import register_provider
from ajolopy.providers.gemini import GeminiProvider


@pytest.fixture(autouse=True)
def ensure_provider_registered_and_clean_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The parent isolate_registry fixture clears _PROVIDERS at the start of
    # every test, so we must re-register GeminiProvider here for tests in
    # this directory to find it in the registry.
    with contextlib.suppress(ValueError):
        register_provider("gemini", GeminiProvider)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # The SDK also reads GOOGLE_API_KEY; clear it so the "missing env var"
    # test reaches the framework's typed error instead of the SDK fallback.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture
def with_gemini_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a fake GEMINI_API_KEY for the duration of the test."""
    fake = "AIza-test-only"
    monkeypatch.setenv("GEMINI_API_KEY", fake)
    return fake


def make_generate_response(
    *,
    text: str = "hello",
    finish_reason: str = "STOP",
    prompt_token_count: int = 10,
    response_token_count: int = 5,
    function_calls: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like a ``GenerateContentResponse``.

    Gemini's real Pydantic models expose ``candidates[0].content.parts``
    (a list of typed ``Part``s), ``candidates[0].finish_reason`` and
    ``usage_metadata.{prompt_token_count, response_token_count}``. The
    converter only reads these attributes, so a SimpleNamespace tree is
    enough — no real SDK objects involved.
    """
    parts: list[SimpleNamespace] = []
    if text:
        parts.append(SimpleNamespace(text=text, function_call=None))
    for fc in function_calls or []:
        parts.append(
            SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(
                    id=fc.get("id", ""),
                    name=fc["name"],
                    args=fc.get("args", {}),
                ),
            )
        )
    content = SimpleNamespace(parts=parts, role="model")
    candidate = SimpleNamespace(
        content=content,
        finish_reason=finish_reason,
        index=0,
    )
    usage = SimpleNamespace(
        prompt_token_count=prompt_token_count,
        response_token_count=response_token_count,
        total_token_count=prompt_token_count + response_token_count,
    )
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


def make_stream_chunk(
    *,
    text: str | None = None,
    finish_reason: str | None = None,
    function_calls: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like a streaming ``GenerateContentResponse``.

    Each Gemini stream push carries the same shape as the non-streaming
    response — a list of candidates with incremental ``parts`` plus an
    optional ``finish_reason`` on the terminal push.
    """
    parts: list[SimpleNamespace] = []
    if text is not None:
        parts.append(SimpleNamespace(text=text, function_call=None))
    for fc in function_calls or []:
        parts.append(
            SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(
                    id=fc.get("id", ""),
                    name=fc["name"],
                    args=fc.get("args", {}),
                ),
            )
        )
    content = SimpleNamespace(parts=parts, role="model")
    candidate = SimpleNamespace(
        content=content,
        finish_reason=finish_reason,
        index=0,
    )
    return SimpleNamespace(candidates=[candidate], usage_metadata=None)


class _AsyncStreamIterator:
    """Minimal async iterator over a list of stream events.

    Tracks ``aclose_called`` so tests can assert the provider cancels the
    underlying SDK stream when the caller bails out early. Optional
    ``raise_after`` raises the supplied exception after yielding the
    listed events — exercises the SDK-error-mid-stream path.
    """

    def __init__(
        self,
        events: list[Any],
        *,
        raise_after: BaseException | None = None,
    ) -> None:
        self._events = events
        self._index = 0
        self._raise_after = raise_after
        self.aclose_called = False

    def __aiter__(self) -> _AsyncStreamIterator:
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            if self._raise_after is not None:
                raise self._raise_after
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def aclose(self) -> None:
        self.aclose_called = True


def make_async_client(
    *,
    generate_return: Any | None = None,
    generate_side_effect: BaseException | None = None,
    stream_events: list[Any] | None = None,
    stream_raise_after: BaseException | None = None,
    embed_return: Any | None = None,
    embed_side_effect: BaseException | None = None,
    count_tokens_return: Any | None = None,
    count_tokens_side_effect: BaseException | None = None,
) -> MagicMock:
    """Build a MagicMock-shaped Gemini client with mocked ``aio.models`` API.

    ``aio.models.generate_content`` and ``aio.models.embed_content`` are
    ``AsyncMock``s; ``aio.models.generate_content_stream`` is a plain
    callable returning the supplied async iterator so tests can assert
    on ``aclose_called``. ``count_tokens`` is also an ``AsyncMock`` so
    the provider's sync wrapper can ``asyncio.run`` it.
    """
    client = MagicMock(name="genai.Client")

    default_response = generate_return if generate_return is not None else make_generate_response()
    generate_mock = AsyncMock(name="aio.models.generate_content")
    if generate_side_effect is not None:
        generate_mock.side_effect = generate_side_effect
    else:
        generate_mock.return_value = default_response
    client.aio.models.generate_content = generate_mock

    stream_iterator = _AsyncStreamIterator(
        stream_events or [],
        raise_after=stream_raise_after,
    )

    def _stream(**_kwargs: Any) -> Any:
        return stream_iterator

    client.aio.models.generate_content_stream = MagicMock(
        name="aio.models.generate_content_stream",
        side_effect=_stream,
    )
    # Expose the stream iterator on the mock so tests can introspect aclose().
    client._stream_iterator = stream_iterator

    default_embed = embed_return if embed_return is not None else SimpleNamespace(embeddings=[])
    embed_mock = AsyncMock(name="aio.models.embed_content")
    if embed_side_effect is not None:
        embed_mock.side_effect = embed_side_effect
    else:
        embed_mock.return_value = default_embed
    client.aio.models.embed_content = embed_mock

    count_mock = AsyncMock(name="aio.models.count_tokens")
    if count_tokens_side_effect is not None:
        count_mock.side_effect = count_tokens_side_effect
    elif count_tokens_return is not None:
        count_mock.return_value = count_tokens_return
    else:
        count_mock.return_value = SimpleNamespace(total_tokens=0)
    client.aio.models.count_tokens = count_mock

    return client


def make_embeddings_response(vectors: list[list[float]]) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like an ``EmbedContentResponse``."""
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=v) for v in vectors],
        metadata=None,
    )
