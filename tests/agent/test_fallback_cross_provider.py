"""Cross-provider fallback integration tests (AJ-23).

Mocks two distinct provider classes — Anthropic-like and OpenAI-like —
plus a Gemini-like fake to verify the fallback chain handles transitions
between providers (not only between models within one provider). Each
test inspects:

- the ``gen_ai.system`` label on each chat span (proves the right
  provider class was instantiated),
- the ``gen_ai.chat.fallback`` event's ``from_provider`` / ``to_provider``
  attributes,
- the existing provider cache contract ("instantiation happens only once
  per provider key").
"""

from collections.abc import Iterator
from typing import override

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.observability.conventions import (
    AJOLOPY_FALLBACK_FROM_PROVIDER,
    AJOLOPY_FALLBACK_TO_PROVIDER,
    GEN_AI_CHAT_FALLBACK_EVENT,
)
from ajolopy.providers import (
    LLMProviderError,
    Message,
    Response,
    Tool,
    register_provider,
)
from tests.agent.conftest import FakeProvider
from tests.observability.conftest import ensure_session_provider


@pytest.fixture
def tracer_provider() -> Iterator[InMemorySpanExporter]:
    exporter = ensure_session_provider()
    exporter.clear()
    try:
        yield exporter
    finally:
        exporter.clear()


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


class _AnthropicFails(FakeProvider):
    """Anthropic-like fake that always raises on ``complete``."""

    GEN_AI_SYSTEM = "anthropic"
    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1

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


class _OpenAIOk(FakeProvider):
    """OpenAI-like fake that returns a happy response."""

    GEN_AI_SYSTEM = "openai"
    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1


class _OpenAIFails(FakeProvider):
    """OpenAI-like fake that always raises."""

    GEN_AI_SYSTEM = "openai"
    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1

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
        raise LLMProviderError(f"openai down: {model}")


class _GeminiOk(FakeProvider):
    """Gemini-like fake that returns a happy response."""

    GEN_AI_SYSTEM = "gcp.gemini"
    instance_count = 0

    def __init__(self) -> None:
        super().__init__()
        type(self).instance_count += 1


@pytest.mark.asyncio
async def test_anthropic_to_openai_cross_provider_fallback(
    tracer_provider: InMemorySpanExporter,
) -> None:
    _AnthropicFails.instance_count = 0
    _OpenAIOk.instance_count = 0
    register_provider("anthropic", _AnthropicFails, overwrite=True)
    register_provider("openai", _OpenAIOk, overwrite=True)

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback="gpt-4o-mini",
    )
    class Demo:
        pass

    answer = await Demo().run("hello")  # type: ignore[attr-defined]
    assert "gpt-4o-mini" in answer

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    assert {s.name for s in chat_spans} == {
        "chat claude-sonnet-4-7",
        "chat gpt-4o-mini",
    }
    secondary = next(s for s in chat_spans if s.name == "chat gpt-4o-mini")
    events = [e for e in secondary.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert len(events) == 1
    attrs = dict(events[0].attributes or {})
    assert attrs[AJOLOPY_FALLBACK_FROM_PROVIDER] == "anthropic"
    assert attrs[AJOLOPY_FALLBACK_TO_PROVIDER] == "openai"

    # Each provider key is instantiated exactly once (AJ-23 spec).
    assert _AnthropicFails.instance_count == 1
    assert _OpenAIOk.instance_count == 1


@pytest.mark.asyncio
async def test_openai_to_gemini_cross_provider_fallback(
    tracer_provider: InMemorySpanExporter,
) -> None:
    _OpenAIFails.instance_count = 0
    _GeminiOk.instance_count = 0
    register_provider("openai", _OpenAIFails, overwrite=True)
    register_provider("gemini", _GeminiOk, overwrite=True)

    @Agent(
        model="gpt-4o-mini",
        system="…",
        fallback="gemini-1.5-flash",
    )
    class Demo:
        pass

    answer = await Demo().run("hello")  # type: ignore[attr-defined]
    assert "gemini-1.5-flash" in answer

    chat_spans = _find(list(tracer_provider.get_finished_spans()), "chat ")
    assert {s.name for s in chat_spans} == {
        "chat gpt-4o-mini",
        "chat gemini-1.5-flash",
    }
    fallback_span = next(s for s in chat_spans if s.name == "chat gemini-1.5-flash")
    events = [e for e in fallback_span.events if e.name == GEN_AI_CHAT_FALLBACK_EVENT]
    assert len(events) == 1
    attrs = dict(events[0].attributes or {})
    assert attrs[AJOLOPY_FALLBACK_FROM_PROVIDER] == "openai"
    assert attrs[AJOLOPY_FALLBACK_TO_PROVIDER] == "gemini"

    assert _OpenAIFails.instance_count == 1
    assert _GeminiOk.instance_count == 1


@pytest.mark.asyncio
async def test_two_models_same_provider_share_one_instance() -> None:
    """``_ensure_provider(i)`` reuses the cached LLMProvider per resolved key.

    AJ-69 made fallback instantiation lazy, so we materialise the two
    OpenAI fallback entries via ``_ensure_provider`` before asserting
    the dedup contract still holds.
    """

    _OpenAIOk.instance_count = 0
    register_provider("openai", _OpenAIOk, overwrite=True)
    register_provider("anthropic", _AnthropicFails, overwrite=True)

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        fallback=["gpt-4o-mini", "gpt-4o"],
    )
    class Demo:
        pass

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    # Materialise the two fallback entries so the dedup check sees real
    # instances (post-AJ-69 they start as ``None``).
    runtime._ensure_provider(1)
    runtime._ensure_provider(2)
    providers = [entry[1] for entry in runtime._models]
    # Three models, two providers (anthropic + openai). The two openai
    # models must share the same instance.
    assert providers[1] is providers[2]
    assert _OpenAIOk.instance_count == 1
