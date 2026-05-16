"""Tests for :func:`ajolopy.eval.metrics.llm_judge` using a fake LLM provider.

The fake exposes ``responses`` (a queue of strings to return as the
next ``Response.text``), ``raise_on_complete`` (override to raise an
:class:`LLMProviderError`), ``call_count`` (number of completion
calls), and ``last_prompt`` (the most recent prompt text) — enough
to lock the contract without touching the network.
"""

from collections.abc import AsyncIterator
from typing import override

import pytest

from ajolopy.eval.metrics import (
    JudgeCache,
    MetricsConfigError,
    MetricsRuntimeError,
    llm_judge,
)
from ajolopy.eval.metrics.judge import _DEFAULT_JUDGE_CACHE
from ajolopy.eval.results import EvalOutput
from ajolopy.providers import (
    Chunk,
    LLMProvider,
    LLMProviderError,
    Message,
    Response,
    Tool,
)


class FakeLLMProvider(LLMProvider):
    """Minimal :class:`LLMProvider` returning scripted responses."""

    def __init__(self) -> None:
        self.responses: list[str] = []
        self.call_count: int = 0
        self.last_prompt: str | None = None
        self.last_kwargs: dict[str, object] = {}
        self.raise_on_complete: BaseException | None = None

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
        self.call_count += 1
        self.last_prompt = messages[-1].content if messages else None
        self.last_kwargs = {
            "model": model,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "cache": cache,
        }
        if self.raise_on_complete is not None:
            exc = self.raise_on_complete
            raise exc
        text = self.responses.pop(0) if self.responses else "0.5"
        return Response(text=text, tokens_in=1, tokens_out=1, finish_reason="stop")

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
        async def _empty() -> AsyncIterator[Chunk]:
            if False:
                yield Chunk(delta="")

        return _empty()

    @override
    async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
        return [[0.0]]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        return len(text)

    @override
    def supports_prompt_caching(self) -> bool:
        return False

    @override
    def supports_tool_calling(self) -> bool:
        return False


def _eval_output(text: str) -> EvalOutput:
    return EvalOutput(text=text, latency_ms=1.0, cost_usd=None, trace_id=None, raw=text)


@pytest.fixture(autouse=True)
def clear_default_cache() -> None:
    _DEFAULT_JUDGE_CACHE.clear()


@pytest.mark.asyncio
async def test_simple_0_to_1_response() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["0.85"]
    score = await llm_judge(
        "the output",
        criterion="is it helpful?",
        model="claude-opus-4-7",
        provider=fake,
    )
    assert score == pytest.approx(0.85)
    assert fake.call_count == 1


@pytest.mark.asyncio
async def test_one_to_five_scale_rescaled() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["   The score is 4 out of 5."]
    score = await llm_judge(
        "the output",
        criterion="rate it",
        model="claude-opus-4-7",
        scale="1-5",
        provider=fake,
    )
    # (4 - 1) / 4 = 0.75
    assert score == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_above_range_clamped() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["1.5"]
    score = await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)
    assert score == 1.0


@pytest.mark.asyncio
async def test_below_range_clamped() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["-0.5"]
    score = await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)
    assert score == 0.0


@pytest.mark.asyncio
async def test_no_numeric_raises_metrics_runtime_error() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["I cannot give a number, sorry."]
    with pytest.raises(MetricsRuntimeError, match="could not parse a number"):
        await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)


@pytest.mark.asyncio
async def test_expected_none_omits_block() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["1"]
    await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)
    assert fake.last_prompt is not None
    assert "Expected" not in fake.last_prompt
    assert "Ideal" not in fake.last_prompt


@pytest.mark.asyncio
async def test_expected_string_includes_block() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["1"]
    await llm_judge(
        "out",
        criterion="x",
        model="claude-opus-4-7",
        expected="the ideal answer",
        provider=fake,
    )
    assert fake.last_prompt is not None
    assert "the ideal answer" in fake.last_prompt
    # Either "Expected" or "Ideal" is the marker keyword the spec
    # documents — we use "Ideal/Expected" in the template.
    assert "Ideal" in fake.last_prompt or "Expected" in fake.last_prompt


@pytest.mark.asyncio
async def test_cache_true_short_circuits() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["0.8", "0.1"]
    score1 = await llm_judge(
        "out", criterion="x", model="claude-opus-4-7", cache=True, provider=fake
    )
    score2 = await llm_judge(
        "out", criterion="x", model="claude-opus-4-7", cache=True, provider=fake
    )
    assert score1 == score2 == pytest.approx(0.8)
    assert fake.call_count == 1


@pytest.mark.asyncio
async def test_cache_false_invokes_every_time() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["0.8", "0.1"]
    s1 = await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)
    s2 = await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)
    assert s1 == pytest.approx(0.8)
    assert s2 == pytest.approx(0.1)
    assert fake.call_count == 2


@pytest.mark.asyncio
async def test_shared_judge_cache_survives_calls() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["0.4", "0.9"]
    cache = JudgeCache()
    s1 = await llm_judge("out", criterion="x", model="claude-opus-4-7", cache=cache, provider=fake)
    s2 = await llm_judge("out", criterion="x", model="claude-opus-4-7", cache=cache, provider=fake)
    assert s1 == s2 == pytest.approx(0.4)
    assert fake.call_count == 1
    assert len(cache) == 1


@pytest.mark.asyncio
async def test_provider_error_bubbles_unwrapped() -> None:
    fake = FakeLLMProvider()
    fake.raise_on_complete = LLMProviderError("transport boom")
    with pytest.raises(LLMProviderError, match="transport boom"):
        await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)


@pytest.mark.asyncio
async def test_eval_output_reduced_to_text() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["1.0"]
    await llm_judge(
        _eval_output("the actual output text"),
        criterion="x",
        model="claude-opus-4-7",
        provider=fake,
    )
    assert fake.last_prompt is not None
    assert "the actual output text" in fake.last_prompt


@pytest.mark.asyncio
async def test_plain_str_used_verbatim() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["1.0"]
    await llm_judge(
        "this exact text",
        criterion="x",
        model="claude-opus-4-7",
        provider=fake,
    )
    assert fake.last_prompt is not None
    assert "this exact text" in fake.last_prompt


@pytest.mark.asyncio
async def test_cache_key_includes_model() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["0.2", "0.9"]
    cache = JudgeCache()
    s1 = await llm_judge("out", criterion="x", model="model-a", cache=cache, provider=fake)
    s2 = await llm_judge("out", criterion="x", model="model-b", cache=cache, provider=fake)
    # Different models => different cache keys => two provider calls.
    assert s1 == pytest.approx(0.2)
    assert s2 == pytest.approx(0.9)
    assert fake.call_count == 2
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_judge_calls_provider_with_temperature_zero_and_short_max_tokens() -> None:
    fake = FakeLLMProvider()
    fake.responses = ["1.0"]
    await llm_judge("out", criterion="x", model="claude-opus-4-7", provider=fake)
    assert fake.last_kwargs["temperature"] == 0.0
    assert fake.last_kwargs["max_tokens"] == 50
    assert fake.last_kwargs["cache"] is False
    assert fake.last_kwargs["tools"] is None


@pytest.mark.asyncio
async def test_invalid_output_type_raises_config_error() -> None:
    fake = FakeLLMProvider()
    with pytest.raises(MetricsConfigError, match="llm_judge requires str or EvalOutput"):
        await llm_judge(
            42,
            criterion="x",
            model="claude-opus-4-7",
            provider=fake,
        )
