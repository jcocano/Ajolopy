"""Tests for :func:`ajolopy.eval.metrics.not_contains`."""

import pytest

from ajolopy.eval.metrics import MetricsConfigError, not_contains
from ajolopy.eval.results import EvalOutput


def _eval_output(text: str) -> EvalOutput:
    return EvalOutput(text=text, latency_ms=1.0, cost_usd=None, trace_id=None, raw=text)


def test_absent_needle_returns_one() -> None:
    assert not_contains("hello", "world") == 1.0


def test_present_needle_returns_zero() -> None:
    assert not_contains("hello world", "hello") == 0.0


def test_safety_check_use_case() -> None:
    assert not_contains("here is the data", ["api_key", "password"]) == 1.0
    assert not_contains("api_key=abc123", ["api_key", "password"]) == 0.0


def test_accepts_eval_output_input() -> None:
    assert not_contains(_eval_output("hello"), "world") == 1.0
    assert not_contains(_eval_output("hello"), "hello") == 0.0


def test_empty_needles_raises() -> None:
    with pytest.raises(MetricsConfigError, match="not_contains: needles is empty"):
        not_contains("text", [])


def test_case_insensitive_default() -> None:
    # Default is case-insensitive (mirrors ``contains``); an upper-cased
    # needle still matches and inverts to 0.0.
    assert not_contains("API_KEY=xyz", "api_key") == 0.0


def test_all_mode_inverted() -> None:
    # ``mode="all"`` on contains => 1.0 when every needle present;
    # not_contains inverts.
    assert not_contains("a b c", ["a", "b"], mode="all") == 0.0
    assert not_contains("a b c", ["a", "x"], mode="all") == 1.0
