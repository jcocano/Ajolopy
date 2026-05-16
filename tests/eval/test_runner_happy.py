"""Happy-path tests for :class:`EvalRunner`.

Targets are mocked at the provider boundary so no real LLM calls run
in CI. The agent under test always echoes a known string per case;
metrics consume that string to produce deterministic scores.
"""

from pathlib import Path

import pytest

from ajolopy import Agent, Eval, Metric, Tool
from ajolopy.eval import EvalRun, EvalRunner
from ajolopy.providers import Response, ToolCall


@pytest.mark.asyncio
async def test_single_metric_returns_score_1(scripted_fake: type, fixtures_dir: Path) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    # support.jsonl has 3 cases; queue 3 known responses.
    provider.responses = [
        Response(text="r1", tokens_in=1, tokens_out=1, finish_reason="stop"),
        Response(text="r2", tokens_in=1, tokens_out=1, finish_reason="stop"),
        Response(text="r3", tokens_in=1, tokens_out=1, finish_reason="stop"),
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def always_pass(self, output, expected) -> float:
            return 1.0

    run = await EvalRunner().run(_Suite)
    assert isinstance(run, EvalRun)
    assert run.passed
    assert run.aggregate_score == pytest.approx(1.0)
    assert run.suite == "_Suite"
    assert run.target_kind == "agent"
    assert run.target_name == "Support"
    assert len(run.cases) == 3


@pytest.mark.asyncio
async def test_threshold_check_fails_when_score_below(
    scripted_fake: type, fixtures_dir: Path
) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r1", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"), threshold=0.9)
    class _Suite:
        @Metric
        def half(self, output, expected) -> float:
            return 0.5

    run = await EvalRunner().run(_Suite)
    assert not run.passed
    assert run.aggregate_score == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_weighted_aggregate_formula(scripted_fake: type, fixtures_dir: Path) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text=f"r{i}", tokens_in=1, tokens_out=1, finish_reason="stop") for i in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric(weight=1.0)
        def alpha(self, output, expected) -> float:
            return 1.0

        @Metric(weight=3.0)
        def beta(self, output, expected) -> float:
            return 0.0

    run = await EvalRunner().run(_Suite)
    # alpha aggregate = 1.0, beta = 0.0
    # weighted = (1.0 * 1.0 + 3.0 * 0.0) / (1.0 + 3.0) = 0.25
    assert run.aggregate_score == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_six_aggregators_via_runner(scripted_fake: type, fixtures_dir: Path) -> None:
    """Verify every aggregator runs end-to-end on a fixed per-case sequence."""
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    # 3 cases — the metric reads expected["intent"] to vary the score.
    # support.jsonl intents are: order_status, cancellation, greeting
    score_map = {"order_status": 1.0, "cancellation": 0.5, "greeting": 0.0}
    provider.responses = [
        Response(text="r", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric(aggregator="mean")
        def mean_metric(self, output, expected) -> float:
            return score_map[expected["intent"]]

        @Metric(aggregator="min")
        def min_metric(self, output, expected) -> float:
            return score_map[expected["intent"]]

        @Metric(aggregator="max")
        def max_metric(self, output, expected) -> float:
            return score_map[expected["intent"]]

        @Metric(aggregator="p50")
        def p50_metric(self, output, expected) -> float:
            return score_map[expected["intent"]]

        @Metric(aggregator="p95")
        def p95_metric(self, output, expected) -> float:
            return score_map[expected["intent"]]

        @Metric(aggregator="count_passing", pass_threshold=0.5)
        def count_metric(self, output, expected) -> float:
            return score_map[expected["intent"]]

    run = await EvalRunner().run(_Suite)
    # The three case scores: 1.0, 0.5, 0.0
    assert run.metrics["mean_metric"].aggregate == pytest.approx(0.5)
    assert run.metrics["min_metric"].aggregate == pytest.approx(0.0)
    assert run.metrics["max_metric"].aggregate == pytest.approx(1.0)
    assert run.metrics["p50_metric"].aggregate == pytest.approx(0.5)
    # count_passing with pass_threshold=0.5: two of three values clear.
    assert run.metrics["count_metric"].aggregate == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_case_ordering_matches_dataset(scripted_fake: type, fixtures_dir: Path) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text=f"r{i}", tokens_in=1, tokens_out=1, finish_reason="stop") for i in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    run = await EvalRunner().run(_Suite)
    assert [case.case_index for case in run.cases] == [0, 1, 2]


@pytest.mark.asyncio
async def test_async_metric_is_awaited(scripted_fake: type, fixtures_dir: Path) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        async def llm_judge(self, output, expected) -> float:
            return 0.75

    run = await EvalRunner().run(_Suite)
    assert run.metrics["llm_judge"].aggregate == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_target_invoked_with_case_input(scripted_fake: type, fixtures_dir: Path) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    await EvalRunner().run(_Suite)
    # support.jsonl has 3 cases with messages: where is my order?, cancel my order, hello.
    seen_messages = []
    for call in provider.complete_calls:
        seen_messages.extend(msg.content for msg in call["messages"] if msg.role == "user")
    assert "where is my order?" in seen_messages
    assert "cancel my order" in seen_messages
    assert "hello" in seen_messages


@pytest.mark.asyncio
async def test_tool_calls_captured_into_eval_output(
    scripted_fake: type, fixtures_dir: Path
) -> None:
    """Agent-target cases stamp dispatched tool names onto ``EvalOutput.tool_calls``.

    Locks the cross-cut wired in AJ-26: the runner allocates a fresh
    ``tool_calls_sink=[]`` per case, threads it through
    ``AgentRuntime.run``, and exposes the captured tuple via
    :attr:`EvalOutput.tool_calls`.

    Uses ``concurrency=1`` so the response queue is consumed
    deterministically across the three cases (each case calls the
    provider twice — tool_call round, then final-text round).
    """
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        @Tool(description="Look up an order")
        def lookup_order(self) -> str:
            return "shipped"

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    # Six entries: three (tool_call, final) pairs.
    provider.responses = []
    for i in range(3):
        provider.responses.append(
            Response(
                text="",
                tool_calls=[ToolCall(id=f"c{i}", name="lookup_order", arguments={})],
                tokens_in=1,
                tokens_out=1,
                finish_reason="tool_calls",
            )
        )
        provider.responses.append(
            Response(text=f"done {i}", tokens_in=1, tokens_out=1, finish_reason="stop")
        )

    @Eval(
        agent=Support,
        dataset=str(fixtures_dir / "support.jsonl"),
        threshold=0.0,
        concurrency=1,
    )
    class _Suite:
        @Metric
        def passthrough(self, output, expected) -> float:
            _ = (output, expected)
            return 1.0

    run = await EvalRunner().run(_Suite)
    for case in run.cases:
        assert case.output is not None
        assert case.output.tool_calls == ("lookup_order",)
