"""Smoke test wiring the seven helpers into an ``@Eval`` suite end-to-end.

Uses the project-wide ``scripted_fake`` provider so each case's
output text is deterministic. ``tool_called`` reads from the agent's
``tool_calls_sink`` capture — we test this with both a no-tool case
(``tool_called(output, None)``) and the smoke contract.
"""

from pathlib import Path

import pytest

from ajolopy import Agent, Eval, Metric
from ajolopy.eval import EvalRunner
from ajolopy.eval.metrics import (
    contains,
    exact_match,
    intent_match,
    json_match,
    not_contains,
    tool_called,
)
from ajolopy.providers import Response


@pytest.mark.asyncio
async def test_all_seven_helpers_compose_in_an_eval_suite(
    scripted_fake: type, fixtures_dir: Path
) -> None:
    _ = scripted_fake

    @Agent(model="claude-sonnet-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    # support.jsonl: three cases. Each provider response is the literal
    # text the metrics will score against.
    provider.responses = [
        Response(text='{"intent": "order_status"}', tokens_in=1, tokens_out=1),
        Response(text='{"intent": "cancellation"}', tokens_in=1, tokens_out=1),
        Response(text='{"intent": "greeting"}', tokens_in=1, tokens_out=1),
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"), threshold=0.0)
    class _Suite:
        @Metric
        def exact(self, output, expected) -> float:
            return exact_match(output, '{"intent": "' + expected["intent"] + '"}')

        @Metric
        def jmatch(self, output, expected) -> float:
            return json_match(output, {"intent": expected["intent"]})

        @Metric
        def has_intent(self, output, expected) -> float:
            return contains(output, expected["intent"])

        @Metric
        def no_secrets(self, output, expected) -> float:
            _ = expected
            return not_contains(output, ["api_key", "password"])

        @Metric
        def intent_check(self, output, expected) -> float:
            return intent_match(output, expected["intent"])

        @Metric
        def no_tool_used(self, output, expected) -> float:
            _ = expected
            # The fake agent emits no tool_calls; expectation == "no tool"
            return tool_called(output, None)

    run = await EvalRunner().run(_Suite)
    assert run.aggregate_score == pytest.approx(1.0)
    # Every per-metric aggregate should also be 1.0 (all cases pass each).
    for metric in run.metrics.values():
        assert metric.aggregate == pytest.approx(1.0), metric.name


@pytest.mark.asyncio
async def test_tool_called_reads_runner_captured_tool_calls(
    scripted_fake: type, fixtures_dir: Path
) -> None:
    """``tool_called`` semantics align with the runner's sink capture.

    The fake agent never dispatches tools, so the captured list is
    empty and ``tool_called(output, None)`` returns ``1.0`` for every
    case (negative-space assertion: the field exists, defaults to
    ``()``, and the metric handles it).
    """
    _ = scripted_fake

    @Agent(model="claude-sonnet-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [Response(text="r", tokens_in=1, tokens_out=1) for _ in range(3)]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"), threshold=0.0)
    class _Suite:
        @Metric
        def no_tool(self, output, expected) -> float:
            _ = expected
            return tool_called(output, None)

    run = await EvalRunner().run(_Suite)
    assert run.metrics["no_tool"].aggregate == pytest.approx(1.0)
    for case in run.cases:
        assert case.output is not None
        assert case.output.tool_calls == ()
