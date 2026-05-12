"""Shared fixtures for `@Agent` tests.

A reusable fake `LLMProvider` lets every test register a known-behaving
backend under any provider key. The registry is cleaned between tests by
the parent `tests/providers/conftest.py` fixture.
"""

from typing import TYPE_CHECKING, override

import pytest

from ajolopy.providers import (
    Chunk,
    LLMProvider,
    LLMProviderError,
    Message,
    Response,
    Tool,
    register_provider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeProvider(LLMProvider):
    """Configurable LLMProvider mock — every test instantiates one fresh.

    State on the instance:
    - ``responses``: deque of Response objects returned by complete(). Each
      complete call pops one. If empty, returns a default Response.
    - ``stream_events``: list of Chunk to yield from stream().
    - ``raise_on_complete``: optional exception to raise instead.
    - ``raise_on_stream``: optional exception to raise from the generator.
    - ``complete_calls`` / ``stream_calls``: captured call kwargs for asserts.
    """

    def __init__(self) -> None:
        self.responses: list[Response] = []
        self.stream_events: list[Chunk] = []
        self.raise_on_complete: BaseException | None = None
        self.raise_on_stream: BaseException | None = None
        self.complete_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

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
        self.complete_calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "cache": cache,
            }
        )
        if self.raise_on_complete is not None:
            exc = self.raise_on_complete
            raise exc
        if self.responses:
            return self.responses.pop(0)
        return Response(text=f"reply from {model}", tokens_in=1, tokens_out=2)

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
        self.stream_calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "cache": cache,
            }
        )
        events = list(self.stream_events) or [
            Chunk(delta=f"chunk from {model}", finish_reason="stop")
        ]
        should_raise = self.raise_on_stream

        async def _it() -> AsyncIterator[Chunk]:
            if should_raise is not None:
                raise should_raise
            for event in events:
                yield event

        return _it()

    @override
    async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
        return [[0.0]]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        return len(text)

    @override
    def supports_prompt_caching(self) -> bool:
        return True

    @override
    def supports_tool_calling(self) -> bool:
        return True


class _ConfigErrorProviderCls(FakeProvider):
    """Provider whose constructor raises — simulates missing env var."""

    def __init__(self) -> None:
        msg = "ANTHROPIC_API_KEY missing (simulated)"
        raise LLMProviderError(msg)


@pytest.fixture
def fake_provider_factory() -> type[FakeProvider]:
    """Return the FakeProvider class so each test instantiates fresh state.

    Pattern used by tests:

        provider_instance = fake_provider_factory()  # not used directly
        class P(FakeProvider): pass
        register_provider("anthropic", P)
        provider = P()  # actually managed by the runtime
    """
    return FakeProvider


@pytest.fixture
def register_fake_anthropic() -> type[FakeProvider]:
    """Register FakeProvider under key 'anthropic' and return the class."""
    register_provider("anthropic", FakeProvider, overwrite=True)
    return FakeProvider


@pytest.fixture
def register_config_error_anthropic() -> type[_ConfigErrorProviderCls]:
    """Register a provider whose __init__ raises, for config-validation tests."""
    register_provider("anthropic", _ConfigErrorProviderCls, overwrite=True)
    return _ConfigErrorProviderCls
