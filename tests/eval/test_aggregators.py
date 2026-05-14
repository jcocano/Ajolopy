"""Tests for the six built-in aggregators.

Inputs are the fixed sequence ``[1.0, 0.8, 0.6, 0.4, 0.2]``; the
expected outputs are verified against direct ``statistics`` calls so
the assertions document the math without re-deriving it.
"""

import statistics

import pytest

from ajolopy.eval.aggregators import AGGREGATOR_NAMES, AGGREGATORS, get_aggregator
from ajolopy.eval.errors import MetricConfigError

VALUES = (1.0, 0.8, 0.6, 0.4, 0.2)


def test_aggregator_names_are_six() -> None:
    assert set(AGGREGATOR_NAMES) == {"mean", "min", "max", "p50", "p95", "count_passing"}


def test_mean() -> None:
    assert AGGREGATORS["mean"](VALUES, 0.5) == pytest.approx(statistics.fmean(VALUES))


def test_min() -> None:
    assert AGGREGATORS["min"](VALUES, 0.5) == min(VALUES)


def test_max() -> None:
    assert AGGREGATORS["max"](VALUES, 0.5) == max(VALUES)


def test_p50_matches_median() -> None:
    assert AGGREGATORS["p50"](VALUES, 0.5) == pytest.approx(statistics.median(VALUES))


def test_p95_matches_quantile() -> None:
    expected = statistics.quantiles(VALUES, n=20, method="exclusive")[18]
    assert AGGREGATORS["p95"](VALUES, 0.5) == pytest.approx(expected)


def test_p95_with_single_value_falls_back_to_max() -> None:
    """``statistics.quantiles`` needs >= 2 values; single-case suites use ``max``."""
    assert AGGREGATORS["p95"]((0.7,), 0.5) == 0.7


def test_count_passing_honors_pass_threshold() -> None:
    # values [1.0, 0.8, 0.6, 0.4, 0.2] — at pass_threshold=0.5, three pass.
    assert AGGREGATORS["count_passing"](VALUES, 0.5) == pytest.approx(3 / 5)


def test_count_passing_strict_threshold() -> None:
    # pass_threshold=0.8 — two values clear it (1.0 and 0.8).
    assert AGGREGATORS["count_passing"](VALUES, 0.8) == pytest.approx(2 / 5)


def test_get_aggregator_returns_callable() -> None:
    assert get_aggregator("mean")(VALUES, 0.5) == AGGREGATORS["mean"](VALUES, 0.5)


def test_get_aggregator_unknown_raises() -> None:
    with pytest.raises(MetricConfigError, match="unknown aggregator"):
        get_aggregator("nope")
