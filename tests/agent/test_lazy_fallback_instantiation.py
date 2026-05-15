"""Tests for the AJ-69 lazy fallback provider instantiation contract.

Cover the four behaviors the refactor locks in:

1. A fallback provider's ``__init__`` is NOT called at decoration time
   (the framework no longer needs the fallback's env vars just to
   import the agent module).
2. The first time the runtime advances to a fallback, the missing
   instance is built lazily and cached for subsequent reuse.
3. If a fallback fails to instantiate at fire time, the runtime logs
   a warning and advances to the next entry in the chain.
4. When every entry in the chain fails — instantiation OR
   ``LLMProviderError`` — the raised ``AgentProviderError`` lists
   every model that was attempted and the reason each one failed.
"""

from typing import override

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentProviderError
from ajolopy.providers import (
    LLMProviderError,
    Message,
    Response,
    Tool,
    register_provider,
)

from .conftest import FakeProvider


class _CountingOpenAIOk(FakeProvider):
    """OpenAI-like provider that counts how many times ``__init__`` runs.

    Used to assert "fallback provider is NOT instantiated at decoration
    time" — the count should stay at 0 until the runtime actually fires
    the fallback.
    """

    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1


class _CountingOpenAIThatFailsToInit(FakeProvider):
    """OpenAI-like provider whose ``__init__`` always raises.

    Simulates "fallback env var missing": every attempt to build an
    instance fails with the same ``LLMProviderError`` you'd see from a
    real Anthropic/OpenAI provider when its API key is unset.
    """

    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1
        raise LLMProviderError("OPENAI_API_KEY missing (simulated)")


class _AnthropicFails(FakeProvider):
    """Anthropic-like provider that imports cleanly but always errors on chat."""

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
        raise LLMProviderError(f"anthropic down: {model}")


class _AnthropicFailsToInit(FakeProvider):
    """Anthropic-like provider whose ``__init__`` raises (missing API key)."""

    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1
        raise LLMProviderError("ANTHROPIC_API_KEY missing (simulated)")


def test_fallback_provider_not_instantiated_at_decoration_time() -> None:
    """AJ-69 — primary instantiates eagerly; fallback does NOT.

    Scenario: OpenAI primary OK, Anthropic fallback would fail to
    construct because ``ANTHROPIC_API_KEY`` is missing. With the lazy
    refactor, decoration succeeds and the fallback's ``__init__`` is
    never called.
    """
    _CountingOpenAIOk.instance_count = 0
    _AnthropicFailsToInit.instance_count = 0
    register_provider("openai", _CountingOpenAIOk, overwrite=True)
    register_provider("anthropic", _AnthropicFailsToInit, overwrite=True)

    @Agent(
        model="gpt-4o-mini",
        system="…",
        fallback="claude-haiku-4-5",
    )
    class Demo:
        pass

    # Primary instantiated eagerly — that's the v0.1 contract.
    assert _CountingOpenAIOk.instance_count == 1
    # Fallback NOT instantiated — that's AJ-69's behavioral change.
    assert _AnthropicFailsToInit.instance_count == 0
    # Internal: ``_models`` carries ``None`` in the second slot for the
    # not-yet-built fallback entry.
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert runtime._models[0][1] is not None
    assert runtime._models[1][1] is None


@pytest.mark.asyncio
async def test_fallback_provider_instantiated_lazily_on_first_fire() -> None:
    """Once the primary fails, the fallback's ``__init__`` finally runs."""
    _CountingOpenAIOk.instance_count = 0
    register_provider("anthropic", _AnthropicFails, overwrite=True)
    register_provider("openai", _CountingOpenAIOk, overwrite=True)

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback="gpt-4o-mini",
    )
    class Demo:
        pass

    # Before the call: only the primary is instantiated.
    assert _CountingOpenAIOk.instance_count == 0

    answer = await Demo().run("hello")  # type: ignore[attr-defined]
    assert "gpt-4o-mini" in answer

    # After the fallback fires: the OpenAI fake was built exactly once
    # and cached for the rest of the runtime's lifetime.
    assert _CountingOpenAIOk.instance_count == 1
    # ``_models`` is now fully materialised.
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert runtime._models[0][1] is not None
    assert runtime._models[1][1] is not None


@pytest.mark.asyncio
async def test_fallback_instantiation_failure_advances_to_next_entry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If a fallback can't ``__init__``, the chain advances to the next one."""

    class _GeminiOk(FakeProvider):
        instance_count = 0

        def __init__(self) -> None:
            super().__init__()
            type(self).instance_count += 1

    register_provider("anthropic", _AnthropicFails, overwrite=True)
    register_provider("openai", _CountingOpenAIThatFailsToInit, overwrite=True)
    register_provider("gemini", _GeminiOk, overwrite=True)

    _CountingOpenAIThatFailsToInit.instance_count = 0
    _GeminiOk.instance_count = 0

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback=["gpt-4o-mini", "gemini-1.5-flash"],
    )
    class Demo:
        pass

    # Decoration is clean — fallback ``__init__`` is NOT called.
    assert _CountingOpenAIThatFailsToInit.instance_count == 0

    with caplog.at_level("WARNING", logger="ajolopy.agent.runtime"):
        answer = await Demo().run("hello")  # type: ignore[attr-defined]

    # Gemini answered — that's the second fallback.
    assert "gemini-1.5-flash" in answer
    # The OpenAI fallback's ``__init__`` was attempted exactly once and
    # raised; Gemini was instantiated exactly once.
    assert _CountingOpenAIThatFailsToInit.instance_count == 1
    assert _GeminiOk.instance_count == 1
    # The instantiation failure was surfaced via a WARNING log.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "OPENAI_API_KEY missing" in r.getMessage()
        or "could not instantiate fallback provider" in r.getMessage()
        for r in warnings
    )


@pytest.mark.asyncio
async def test_exhausted_chain_lists_every_attempt_and_reason() -> None:
    """When primary AND every fallback fails, the error names each one.

    Exercises the "both env vars missing" UX: the user sees that
    Anthropic was OK to construct but its chat call failed, AND that
    the OpenAI fallback could not even be instantiated. That diagnostic
    breadth is the practical reason for the lazy refactor.
    """
    register_provider("anthropic", _AnthropicFails, overwrite=True)
    register_provider("openai", _CountingOpenAIThatFailsToInit, overwrite=True)
    _CountingOpenAIThatFailsToInit.instance_count = 0

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback="gpt-4o-mini",
    )
    class Demo:
        pass

    with pytest.raises(AgentProviderError) as excinfo:
        await Demo().run("hello")  # type: ignore[attr-defined]

    message = str(excinfo.value)
    # Both models named in the message.
    assert "claude-sonnet-4-7" in message
    assert "gpt-4o-mini" in message
    # Primary's chat error is captured.
    assert "anthropic down" in message
    # Fallback's instantiation error is captured.
    assert "OPENAI_API_KEY missing" in message
