"""Tests for the fallback chain.

Covers the "Fallback" acceptance group.
"""

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentConfigError, AgentProviderError
from ajolopy.providers import LLMProviderError, Response, register_provider

from .conftest import FakeProvider


class _AlwaysFailFirstThenOk(FakeProvider):
    """Provider that fails on the first model in its chain, succeeds after."""

    def __init__(self) -> None:
        super().__init__()
        self._calls = 0

    async def complete(self, **kwargs: object) -> Response:  # type: ignore[override]
        self._calls += 1
        if self._calls == 1:
            raise LLMProviderError("simulated transient failure")
        return Response(text=f"recovered via {kwargs['model']}", tokens_in=1, tokens_out=1)


@pytest.mark.asyncio
async def test_string_fallback_retries_with_named_model() -> None:
    register_provider("anthropic", _AlwaysFailFirstThenOk)

    @Agent(
        model="claude-opus-4-7",
        system="…",
        fallback="claude-haiku-4-5",
    )
    class Demo:
        pass

    answer = await Demo().run("hello")  # type: ignore[attr-defined]
    assert "claude-haiku-4-5" in answer


@pytest.mark.asyncio
async def test_list_fallback_tries_in_order() -> None:
    register_provider("anthropic", _AlwaysFailFirstThenOk)

    @Agent(
        model="claude-opus-4-7",
        system="…",
        fallback=["claude-opus-4-1", "claude-haiku-4-5"],
    )
    class Demo:
        pass

    answer = await Demo().run("hello")  # type: ignore[attr-defined]
    # First fallback in the list is the one that succeeds.
    assert "claude-opus-4-1" in answer


@pytest.mark.asyncio
async def test_callable_fallback_receives_payload_and_return_is_surfaced(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    class _AlwaysFails(FakeProvider):
        async def complete(self, **kwargs: object) -> Response:  # type: ignore[override]
            raise LLMProviderError("primary down")

    register_provider("anthropic", _AlwaysFails, overwrite=True)

    captured: list[str] = []

    def fallback(message: str) -> str:
        captured.append(message)
        return f"fallback handled: {message}"

    @Agent(model="claude-opus-4-7", system="…", fallback=fallback)
    class Demo:
        pass

    answer = await Demo().run("payload-text")  # type: ignore[attr-defined]
    assert captured == ["payload-text"]
    assert answer == "fallback handled: payload-text"


def test_fallback_with_unregistered_provider_fails_at_decoration(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic
    # OpenAI provider is not registered → AgentConfigError at decoration time.
    with pytest.raises(AgentConfigError, match="openai"):

        @Agent(
            model="claude-opus-4-7",
            system="…",
            fallback="gpt-4o-mini",
        )
        class _Demo:
            pass


@pytest.mark.asyncio
async def test_exhausted_chain_raises_agent_provider_error(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    class _AlwaysFails(FakeProvider):
        async def complete(self, **kwargs: object) -> Response:  # type: ignore[override]
            raise LLMProviderError("never works")

    register_provider("anthropic", _AlwaysFails, overwrite=True)

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    with pytest.raises(AgentProviderError, match="exhausted"):
        await Demo().run("hello")  # type: ignore[attr-defined]
