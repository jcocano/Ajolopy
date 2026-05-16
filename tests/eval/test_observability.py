"""Span emission and cost roll-up tests for :class:`EvalRunner`.

Spans are collected via the shared session-level
:class:`InMemorySpanExporter` (``tests/observability/conftest.py``).
The exporter is cleared at the start of each test so the assertions
see only the spans produced by the run under test.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent, Eval, Metric
from ajolopy.eval import EvalRunner
from ajolopy.observability import (
    AJOLOPY_COST_USD_TOTAL,
    AJOLOPY_EVAL_AGGREGATE_SCORE,
    AJOLOPY_EVAL_CASE_INDEX,
    AJOLOPY_EVAL_CASE_PASSED,
    AJOLOPY_EVAL_CONCURRENCY,
    AJOLOPY_EVAL_PASSED,
    AJOLOPY_EVAL_SCORE_PREFIX,
    AJOLOPY_EVAL_SUITE,
    AJOLOPY_EVAL_TARGET_KIND,
    AJOLOPY_EVAL_THRESHOLD,
    Catalog,
    ModelPrice,
)
from ajolopy.observability.pricing import set_default_catalog
from ajolopy.providers import Response
from tests.observability.conftest import ensure_session_provider


@pytest.fixture
def tracer_provider() -> Iterator[InMemorySpanExporter]:
    exporter = ensure_session_provider()
    exporter.clear()
    try:
        yield exporter
    finally:
        exporter.clear()


@pytest.fixture
def reset_active_catalog() -> Iterator[None]:
    try:
        yield
    finally:
        set_default_catalog(None)


@pytest.fixture
def billable_catalog() -> Catalog:
    return Catalog(
        {
            "claude-opus-4-7": ModelPrice(
                input_cost_per_token=3e-6,
                output_cost_per_token=15e-6,
            ),
        }
    )


@pytest.mark.asyncio
async def test_eval_run_span_carries_documented_attrs(
    scripted_fake: type, fixtures_dir: Path, tracer_provider: InMemorySpanExporter
) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(
        agent=Support,
        dataset=str(fixtures_dir / "support.jsonl"),
        threshold=0.5,
        concurrency=3,
    )
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    await EvalRunner().run(_Suite)
    spans = list(tracer_provider.get_finished_spans())
    run_spans = [s for s in spans if s.name.startswith("eval.run")]
    assert len(run_spans) == 1
    attrs = run_spans[0].attributes or {}
    assert attrs.get(AJOLOPY_EVAL_SUITE) == "_Suite"
    assert attrs.get(AJOLOPY_EVAL_TARGET_KIND) == "agent"
    assert attrs.get(AJOLOPY_EVAL_THRESHOLD) == pytest.approx(0.5)
    assert attrs.get(AJOLOPY_EVAL_CONCURRENCY) == 3
    assert attrs.get(AJOLOPY_EVAL_AGGREGATE_SCORE) == pytest.approx(1.0)
    assert attrs.get(AJOLOPY_EVAL_PASSED) is True


@pytest.mark.asyncio
async def test_case_spans_nested_under_run_span(
    scripted_fake: type, fixtures_dir: Path, tracer_provider: InMemorySpanExporter
) -> None:
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
    spans = list(tracer_provider.get_finished_spans())
    run_span = next(s for s in spans if s.name.startswith("eval.run"))
    case_spans = [s for s in spans if s.name.startswith("eval.case")]
    assert len(case_spans) == 3
    # Every case span's parent should be the eval.run span.
    run_context = run_span.context
    assert run_context is not None
    for case_span in case_spans:
        parent = case_span.parent
        assert parent is not None
        assert parent.span_id == run_context.span_id


@pytest.mark.asyncio
async def test_case_spans_have_per_metric_score_attributes(
    scripted_fake: type, fixtures_dir: Path, tracer_provider: InMemorySpanExporter
) -> None:
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
        def helpful(self, output, expected) -> float:
            return 0.7

    await EvalRunner().run(_Suite)
    spans = list(tracer_provider.get_finished_spans())
    case_spans = [s for s in spans if s.name.startswith("eval.case")]
    assert case_spans
    for case_span in case_spans:
        attrs = case_span.attributes or {}
        assert attrs.get(f"{AJOLOPY_EVAL_SCORE_PREFIX}helpful") == pytest.approx(0.7)
        assert AJOLOPY_EVAL_CASE_INDEX in attrs
        assert attrs.get(AJOLOPY_EVAL_CASE_PASSED) is True


@pytest.mark.asyncio
async def test_run_span_rolls_up_cost_total(
    scripted_fake: type,
    fixtures_dir: Path,
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    billable_catalog: Catalog,
) -> None:
    _ = (scripted_fake, reset_active_catalog)
    set_default_catalog(billable_catalog)

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r", tokens_in=10, tokens_out=5, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    run = await EvalRunner().run(_Suite)
    spans = list(tracer_provider.get_finished_spans())
    run_span = next(s for s in spans if s.name.startswith("eval.run"))
    rolled_up = (run_span.attributes or {}).get(AJOLOPY_COST_USD_TOTAL)
    assert rolled_up is not None
    # Each case has cost > 0; total should equal sum of per-case costs.
    expected_total = sum(
        c.output.cost_usd
        for c in run.cases
        if c.output is not None and c.output.cost_usd is not None
    )
    assert rolled_up == pytest.approx(expected_total)
