"""Tests for :func:`compare_runs` regression detection.

Run snapshots are built by hand here so the deltas are deterministic
and do not depend on the runner's behaviour.
"""

import math
from collections.abc import Mapping

import pytest

from ajolopy.eval import (
    EvalCaseResult,
    EvalComparisonError,
    EvalMetricResult,
    EvalRun,
    compare_runs,
)


def _make_run(
    *,
    suite: str = "S",
    timestamp: str = "2026-01-01T00:00:00Z",
    metrics: Mapping[str, EvalMetricResult] | None = None,
    cases: tuple[EvalCaseResult, ...] | None = None,
    dataset_sha256: str | None = "sha-1",
    aggregate_score: float = 0.5,
    passed: bool = True,
) -> EvalRun:
    return EvalRun(
        suite=suite,
        timestamp=timestamp,
        target_kind="agent",
        target_name="Target",
        dataset_path="/abs/d.jsonl",
        dataset_sha256=dataset_sha256,
        threshold=0.5,
        concurrency=5,
        metrics=metrics or {},
        cases=cases or (),
        aggregate_score=aggregate_score,
        passed=passed,
    )


def _make_metric(name: str, aggregate: float, weight: float = 1.0) -> EvalMetricResult:
    return EvalMetricResult(
        name=name,
        aggregator="mean",
        weight=weight,
        pass_threshold=0.5,
        values=(aggregate,),
        aggregate=aggregate,
        passed=aggregate >= 0.5,
    )


def _make_case(index: int, passed: bool) -> EvalCaseResult:
    return EvalCaseResult(
        case_index=index,
        input={},
        expected={},
        output=None,
        metric_scores={},
        error=None if passed else "boom",
        passed=passed,
    )


def test_equal_runs_have_no_regressions() -> None:
    prev = _make_run(metrics={"m": _make_metric("m", 0.9)})
    curr = _make_run(metrics={"m": _make_metric("m", 0.9)})
    diff = compare_runs(prev, curr)
    assert not diff.metric_deltas["m"].is_regression
    assert diff.metric_deltas["m"].delta == pytest.approx(0.0)


def test_regression_at_0_05_drop() -> None:
    prev = _make_run(metrics={"m": _make_metric("m", 0.9)})
    curr = _make_run(metrics={"m": _make_metric("m", 0.85)})
    diff = compare_runs(prev, curr)
    assert diff.metric_deltas["m"].is_regression
    assert diff.metric_deltas["m"].delta == pytest.approx(-0.05)


def test_no_regression_below_1e3_floor() -> None:
    prev = _make_run(metrics={"m": _make_metric("m", 0.9)})
    curr = _make_run(metrics={"m": _make_metric("m", 0.8995)})
    diff = compare_runs(prev, curr)
    assert not diff.metric_deltas["m"].is_regression


def test_newly_failing_case_indices() -> None:
    prev = _make_run(
        cases=(_make_case(0, True), _make_case(1, True), _make_case(2, False)),
    )
    curr = _make_run(
        cases=(_make_case(0, False), _make_case(1, True), _make_case(2, False)),
    )
    diff = compare_runs(prev, curr)
    assert diff.newly_failing_case_indices == (0,)
    assert diff.newly_passing_case_indices == ()


def test_newly_passing_case_indices() -> None:
    prev = _make_run(
        cases=(_make_case(0, False), _make_case(1, False), _make_case(2, True)),
    )
    curr = _make_run(
        cases=(_make_case(0, True), _make_case(1, False), _make_case(2, True)),
    )
    diff = compare_runs(prev, curr)
    assert diff.newly_passing_case_indices == (0,)


def test_suite_name_mismatch_raises() -> None:
    prev = _make_run(suite="A")
    curr = _make_run(suite="B")
    with pytest.raises(EvalComparisonError, match="suite name"):
        compare_runs(prev, curr)


def test_dataset_sha_mismatch_raises() -> None:
    prev = _make_run(dataset_sha256="sha-1")
    curr = _make_run(dataset_sha256="sha-2")
    with pytest.raises(EvalComparisonError, match="dataset changed"):
        compare_runs(prev, curr)


def test_case_count_mismatch_raises() -> None:
    prev = _make_run(cases=(_make_case(0, True),))
    curr = _make_run(cases=(_make_case(0, True), _make_case(1, True)))
    with pytest.raises(EvalComparisonError, match="case count"):
        compare_runs(prev, curr)


def test_new_metric_is_not_regression() -> None:
    prev = _make_run(metrics={"old": _make_metric("old", 0.9)})
    curr = _make_run(
        metrics={
            "old": _make_metric("old", 0.9),
            "new": _make_metric("new", 0.1),
        }
    )
    diff = compare_runs(prev, curr)
    assert not diff.metric_deltas["new"].is_regression
    assert math.isnan(diff.metric_deltas["new"].prev_aggregate)


def test_compare_skips_dataset_sha_when_either_is_none() -> None:
    # Custom in-memory datasets persist ``None`` for ``dataset_sha256``;
    # the comparator skips the sha check rather than spuriously raising.
    prev = _make_run(dataset_sha256=None)
    curr = _make_run(dataset_sha256="sha-2")
    diff = compare_runs(prev, curr)
    assert diff.suite == "S"
