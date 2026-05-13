"""Shared fixtures and helpers for UniversalOpenAIProvider tests.

The tests *never* hit the network — every interaction with the OpenAI
SDK goes through ``AsyncMock`` shims set up here. All per-prefix env
vars are cleared per-test so the lazy env-var-fallback branch is
reachable deterministically; opt back in with the ``set_api_key``
fixture or ``monkeypatch.setenv`` inside a specific test.
"""

import contextlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ajolopy.providers import register_provider
from ajolopy.providers.universal_openai import UniversalOpenAIProvider

# Env vars covered by the provider's per-prefix table. Cleared on every
# test entry so each test starts from a known-empty baseline.
_PER_PREFIX_ENV_VARS: tuple[str, ...] = (
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def ensure_provider_registered_and_clean_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The parent ``isolate_registry`` fixture clears ``_PROVIDERS`` at
    # the start of every test, so we must re-register
    # UniversalOpenAIProvider here for tests in this directory to find
    # it in the registry.
    with contextlib.suppress(ValueError):
        register_provider("universal-openai", UniversalOpenAIProvider)
    for var in _PER_PREFIX_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def make_chat_completion(
    *,
    text: str = "hello",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    tool_calls: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like an OpenAI ``ChatCompletion`` response.

    OpenAI-compatible APIs return the same Pydantic shape via the SDK,
    so this helper is functionally identical to the AJ-20 fixture.
    """
    raw_tool_calls: list[SimpleNamespace] = []
    for call in tool_calls or []:
        raw_tool_calls.append(
            SimpleNamespace(
                id=call["id"],
                type="function",
                function=SimpleNamespace(
                    name=call["name"],
                    arguments=call["arguments"],
                ),
            )
        )
    message = SimpleNamespace(
        role="assistant",
        content=text or None,
        tool_calls=raw_tool_calls or None,
    )
    choice = SimpleNamespace(
        index=0,
        message=message,
        finish_reason=finish_reason,
    )
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def make_stream_chunk(
    *,
    text: str | None = None,
    finish_reason: str | None = None,
    tool_call_deltas: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like a ``ChatCompletionChunk``."""
    raw_tool_calls: list[SimpleNamespace] = []
    for tcd in tool_call_deltas or []:
        function_payload = tcd.get("function")
        function: SimpleNamespace | None
        if function_payload is None:
            function = None
        else:
            function = SimpleNamespace(
                name=function_payload.get("name"),
                arguments=function_payload.get("arguments"),
            )
        raw_tool_calls.append(
            SimpleNamespace(
                index=tcd.get("index"),
                id=tcd.get("id"),
                type="function",
                function=function,
            )
        )
    delta = SimpleNamespace(
        role=None,
        content=text,
        tool_calls=raw_tool_calls or None,
    )
    choice = SimpleNamespace(
        index=0,
        delta=delta,
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice])


class _AsyncStreamIterator:
    """Minimal async iterator over a list of stream chunks.

    Tracks ``close_called`` so tests can assert the provider cancels
    the underlying SDK stream when the caller bails out early.
    """

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self._index = 0
        self.close_called = False

    def __aiter__(self) -> _AsyncStreamIterator:
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def close(self) -> None:
        self.close_called = True


def make_async_client(
    *,
    create_return: Any | None = None,
    stream_events: list[Any] | None = None,
    create_side_effect: BaseException | None = None,
    embed_return: Any | None = None,
    embed_side_effect: BaseException | None = None,
) -> MagicMock:
    """Build a MagicMock-shaped OpenAI client with mocked chat + embeddings."""
    client = MagicMock(name="AsyncOpenAI")

    default_completion = create_return if create_return is not None else make_chat_completion()
    stream_iterator = _AsyncStreamIterator(stream_events or [])

    async def _create(**kwargs: Any) -> Any:
        if create_side_effect is not None:
            raise create_side_effect
        if kwargs.get("stream"):
            return stream_iterator
        return default_completion

    create_mock = AsyncMock(name="chat.completions.create", side_effect=_create)
    client.chat.completions.create = create_mock
    # Expose the stream iterator so tests can introspect close().
    client._stream_iterator = stream_iterator

    default_embeddings = embed_return if embed_return is not None else SimpleNamespace(data=[])
    embed_mock = AsyncMock(name="embeddings.create")
    if embed_side_effect is not None:
        embed_mock.side_effect = embed_side_effect
    else:
        embed_mock.return_value = default_embeddings
    client.embeddings.create = embed_mock

    return client


def make_embeddings_response(vectors: list[list[float]]) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like an ``embeddings.create`` response."""
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=v, index=i) for i, v in enumerate(vectors)],
        model="universal-embedding",
        usage=SimpleNamespace(prompt_tokens=1, total_tokens=1),
    )
