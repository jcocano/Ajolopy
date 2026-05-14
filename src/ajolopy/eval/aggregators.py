"""The six built-in aggregators for ``@Metric`` per-case values.

Every aggregator collapses a per-case ``Sequence[float]`` into a single
``float``. They share a uniform signature ``(values, pass_threshold) ->
float`` so :class:`~ajolopy.eval.runner.EvalRunner` can dispatch by
name without branching on aggregator family. Aggregators that do not
need the threshold ignore the second argument:

- ``mean`` — arithmetic mean of every per-case value.
- ``min`` — strictest aggregator; one failing case fails the metric.
- ``max`` — most lenient; a single passing case lifts the aggregate.
- ``p50`` — median (50th percentile) computed by
  :func:`statistics.median`.
- ``p95`` — 95th percentile via
  :func:`statistics.quantiles(values, n=20, method="exclusive")[18]`.
  ``statistics.quantiles`` requires ``n >= 1`` AND at least two data
  points; suites with fewer than two cases fall back to ``max(values)``
  so a one-case smoke test still produces a meaningful number.
- ``count_passing`` — fraction of cases whose per-case value cleared
  the metric's own ``pass_threshold``. The only aggregator that
  consults the second argument.

Empty input is rejected by the caller (``EvalRunner`` refuses to run
against an empty dataset, raising :class:`~ajolopy.eval.errors.EvalRunError`),
so every aggregator can assume ``len(values) >= 1``.
"""

import statistics
from collections.abc import Callable, Sequence

from .errors import MetricConfigError

__all__ = [
    "AGGREGATORS",
    "AGGREGATOR_NAMES",
    "Aggregator",
    "get_aggregator",
]


# A uniform aggregator signature lets the runner dispatch by name
# without sprouting one branch per aggregator family. Aggregators that
# do not need the per-metric ``pass_threshold`` ignore the second arg.
Aggregator = Callable[[Sequence[float], float], float]


def _mean(values: Sequence[float], _pass_threshold: float) -> float:
    return statistics.fmean(values)


def _min(values: Sequence[float], _pass_threshold: float) -> float:
    return min(values)


def _max(values: Sequence[float], _pass_threshold: float) -> float:
    return max(values)


def _p50(values: Sequence[float], _pass_threshold: float) -> float:
    return statistics.median(values)


def _p95(values: Sequence[float], _pass_threshold: float) -> float:
    # ``statistics.quantiles`` requires at least two data points. For
    # a one-case smoke test we fall back to the only data point we have
    # (which is both min and max of the singleton set). This keeps
    # ``EvalMetricResult.aggregate`` well-defined regardless of suite
    # size; the caller is responsible for refusing empty datasets.
    if len(values) < 2:
        return max(values)
    return statistics.quantiles(values, n=20, method="exclusive")[18]


def _count_passing(values: Sequence[float], pass_threshold: float) -> float:
    passing = sum(1 for v in values if v >= pass_threshold)
    return passing / len(values)


AGGREGATORS: dict[str, Aggregator] = {
    "mean": _mean,
    "min": _min,
    "max": _max,
    "p50": _p50,
    "p95": _p95,
    "count_passing": _count_passing,
}
"""Name -> aggregator dispatch table. ``@Metric`` validation reads from
this dict so adding a new aggregator means landing one entry here, not
hand-editing the validation message."""


AGGREGATOR_NAMES: tuple[str, ...] = tuple(AGGREGATORS.keys())
"""Stable ordered view used in validation error messages so the user
sees the same six names in the same order on every error."""


def get_aggregator(name: str) -> Aggregator:
    """Look up an aggregator by name or raise :class:`MetricConfigError`.

    Used by :func:`~ajolopy.eval.metric.Metric` at decoration time and
    by :class:`~ajolopy.eval.runner.EvalRunner` at runtime. Centralising
    the lookup keeps the error message identical at both call sites.
    """
    try:
        return AGGREGATORS[name]
    except KeyError as exc:
        raise MetricConfigError(
            f"unknown aggregator {name!r}; expected one of {list(AGGREGATOR_NAMES)!r}."
        ) from exc
