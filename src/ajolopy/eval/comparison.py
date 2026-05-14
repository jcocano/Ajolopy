"""Regression detection between two :class:`EvalRun` snapshots.

:func:`compare_runs` is the primitive the future ``ajolopy eval
--compare-with`` CLI (AJ-27) will sit on top of. It refuses pairs that
cannot be meaningfully compared (different suite, different dataset,
different case count) and computes:

- A per-metric :class:`~ajolopy.eval.results.MetricDelta` for every
  metric present in either run. New metrics (present only in
  ``curr``) carry ``prev_aggregate=NaN`` and are NEVER classified as
  regressions; dropped metrics (present only in ``prev``) carry
  ``curr_aggregate=NaN`` and are also not regressions (the absence is
  reportable on its own; the CLI surfaces it separately).
- ``newly_failing_case_indices`` — cases that flipped ``passed=True``
  in ``prev`` to ``passed=False`` in ``curr``. Sorted ascending.
- ``newly_passing_case_indices`` — the inverse direction.

Regression threshold: ``curr.aggregate < prev.aggregate - 1e-3``. The
floor absorbs floating-point noise from the aggregation pipeline so
a metric whose aggregate dropped by 0.0005 does NOT trip the alarm.
"""

import math

from .errors import EvalComparisonError
from .results import EvalComparison, EvalRun, MetricDelta

__all__ = [
    "REGRESSION_FLOOR",
    "compare_runs",
]


REGRESSION_FLOOR = 1e-3
"""Minimum drop in metric aggregate that counts as a regression.

Absorbs float noise from aggregation; smaller drops are not surfaced
even when the raw arithmetic comparison would catch them."""


def compare_runs(prev: EvalRun, curr: EvalRun) -> EvalComparison:
    """Diff two :class:`EvalRun` snapshots; refuse incomparable pairs.

    The comparison is meaningful only when both runs describe the same
    suite over the same dataset with the same case count. Mismatches
    raise :class:`EvalComparisonError` with an actionable message.
    """
    _validate_pair(prev=prev, curr=curr)

    metric_names = sorted(set(prev.metrics) | set(curr.metrics))
    metric_deltas: dict[str, MetricDelta] = {}
    for name in metric_names:
        prev_metric = prev.metrics.get(name)
        curr_metric = curr.metrics.get(name)
        prev_aggregate = prev_metric.aggregate if prev_metric is not None else math.nan
        curr_aggregate = curr_metric.aggregate if curr_metric is not None else math.nan
        delta = curr_aggregate - prev_aggregate
        # Regressions only apply when both runs include the metric:
        # a new metric or a dropped metric is not a regression per se
        # (the CLI surfaces those events separately).
        is_regression = False
        if prev_metric is not None and curr_metric is not None:
            is_regression = curr_aggregate < prev_aggregate - REGRESSION_FLOOR
        metric_deltas[name] = MetricDelta(
            name=name,
            prev_aggregate=prev_aggregate,
            curr_aggregate=curr_aggregate,
            delta=delta,
            is_regression=is_regression,
        )

    newly_failing: list[int] = []
    newly_passing: list[int] = []
    # ``EvalRun.cases`` is already sorted by ``case_index`` (the
    # runner guarantees this); zip is positional.
    for prev_case, curr_case in zip(prev.cases, curr.cases, strict=True):
        if prev_case.passed and not curr_case.passed:
            newly_failing.append(curr_case.case_index)
        elif not prev_case.passed and curr_case.passed:
            newly_passing.append(curr_case.case_index)

    return EvalComparison(
        suite=curr.suite,
        prev_timestamp=prev.timestamp,
        curr_timestamp=curr.timestamp,
        metric_deltas=metric_deltas,
        newly_failing_case_indices=tuple(sorted(newly_failing)),
        newly_passing_case_indices=tuple(sorted(newly_passing)),
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _validate_pair(*, prev: EvalRun, curr: EvalRun) -> None:
    if prev.suite != curr.suite:
        raise EvalComparisonError(
            f"suite name mismatch: prev={prev.suite!r}, curr={curr.suite!r}. "
            f"compare_runs only compares snapshots of the same @Eval suite."
        )
    if _both_have_sha(prev, curr) and prev.dataset_sha256 != curr.dataset_sha256:
        raise EvalComparisonError(
            "dataset changed between runs; comparisons are only meaningful "
            "for the same dataset. (The CLI will surface a --force flag to "
            "override this check.)"
        )
    if len(prev.cases) != len(curr.cases):
        raise EvalComparisonError(
            f"case count mismatch: prev has {len(prev.cases)} cases, "
            f"curr has {len(curr.cases)}. compare_runs only compares "
            f"snapshots with the same number of cases."
        )


def _both_have_sha(prev: EvalRun, curr: EvalRun) -> bool:
    """Only enforce the sha guard when both runs carry a dataset sha.

    Custom in-memory datasets save ``None`` here; treating ``None``
    as a mismatch would break round-tripping in-memory suites.
    """
    return prev.dataset_sha256 is not None and curr.dataset_sha256 is not None
