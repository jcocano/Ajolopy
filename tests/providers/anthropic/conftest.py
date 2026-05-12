"""Shared fixtures and helpers for AnthropicProvider tests.

The tests *never* hit the network — every interaction with the Anthropic SDK
goes through ``AsyncMock`` shims set up here. ``ANTHROPIC_API_KEY`` is
cleared per-test so the provider's env-var fallback branch is reachable
deterministically; opt back in with ``with_anthropic_key``.
"""

import contextlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ajolopy.providers import register_provider
from ajolopy.providers.anthropic import AnthropicProvider


@pytest.fixture(autouse=True)
def ensure_provider_registered_and_clean_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The parent isolate_registry fixture clears _PROVIDERS at the start of
    # every test, so we must re-register AnthropicProvider here for tests in
    # this directory to find it in the registry.
    with contextlib.suppress(ValueError):
        register_provider("anthropic", AnthropicProvider)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def with_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a fake ANTHROPIC_API_KEY for the duration of the test."""
    fake = "sk-ant-test-only"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake)
    return fake


def make_anthropic_message(
    *,
    text: str = "hello",
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
    tool_uses: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like an Anthropic ``Message`` response.

    Anthropic's real Pydantic models expose ``content`` (list of typed
    blocks), ``usage`` (with ``input_tokens`` / ``output_tokens``), and
    ``stop_reason``. We only need these attributes for the conversion
    helpers in AnthropicProvider, so a SimpleNamespace tree is enough.
    """
    content: list[SimpleNamespace] = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for tu in tool_uses or []:
        content.append(
            SimpleNamespace(
                type="tool_use",
                id=tu["id"],
                name=tu["name"],
                input=tu.get("input", {}),
            )
        )
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
    )


def make_async_client(
    *,
    create_return: Any | None = None,
    stream_events: list[Any] | None = None,
    create_side_effect: BaseException | None = None,
) -> MagicMock:
    """Build a MagicMock-shaped Anthropic client with mocked messages API.

    The .messages.create is an AsyncMock; .messages.stream returns an async
    context manager whose ``__aenter__`` yields an async iterator over the
    supplied events.
    """
    client = MagicMock(name="AsyncAnthropic")

    create_mock = AsyncMock(name="messages.create")
    if create_side_effect is not None:
        create_mock.side_effect = create_side_effect
    elif create_return is not None:
        create_mock.return_value = create_return
    else:
        create_mock.return_value = make_anthropic_message()
    client.messages.create = create_mock

    class _AsyncStreamCM:
        """Minimal async context manager + iterator wrapping a list of events."""

        def __init__(self, events: list[Any]) -> None:
            self._events = events

        async def __aenter__(self) -> _AsyncStreamCM:
            return self

        async def __aexit__(self, *_: Any) -> bool:
            return False

        def __aiter__(self) -> _AsyncStreamCM:
            self._index = 0
            return self

        async def __anext__(self) -> Any:
            if self._index >= len(self._events):
                raise StopAsyncIteration
            event = self._events[self._index]
            self._index += 1
            return event

    def _stream(**_kwargs: Any) -> _AsyncStreamCM:
        return _AsyncStreamCM(stream_events or [])

    client.messages.stream = MagicMock(name="messages.stream", side_effect=_stream)

    return client
