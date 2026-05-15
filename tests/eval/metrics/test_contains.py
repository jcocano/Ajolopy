"""Tests for :func:`ajolopy.eval.metrics.contains`."""

import pytest

from ajolopy.eval.metrics import MetricsConfigError, contains
from ajolopy.eval.results import EvalOutput


def _eval_output(text: str) -> EvalOutput:
    return EvalOutput(text=text, latency_ms=1.0, cost_usd=None, trace_id=None, raw=text)


def test_substring_present() -> None:
    assert contains("hello world", "hello") == 1.0


def test_substring_missing() -> None:
    assert contains("hello world", "missing") == 0.0


def test_case_insensitive_default() -> None:
    assert contains("Hello World", "hello") == 1.0


def test_case_sensitive_kwarg() -> None:
    assert contains("Hello World", "hello", case_sensitive=True) == 0.0
    assert contains("Hello World", "Hello", case_sensitive=True) == 1.0


def test_any_mode_one_match() -> None:
    assert contains("a b c", ["x", "b"], mode="any") == 1.0


def test_any_mode_no_match() -> None:
    assert contains("a b c", ["x", "y"], mode="any") == 0.0


def test_all_mode_full_match() -> None:
    assert contains("a b c", ["a", "b"], mode="all") == 1.0


def test_all_mode_partial_match_fails() -> None:
    assert contains("a b c", ["a", "x"], mode="all") == 0.0


def test_empty_needles_raises() -> None:
    with pytest.raises(MetricsConfigError, match="contains: needles is empty"):
        contains("text", [])


def test_empty_text_no_match() -> None:
    assert contains("", "x") == 0.0


def test_accepts_eval_output_input() -> None:
    assert contains(_eval_output("hello"), "hello") == 1.0
