"""Tests for :func:`ajolopy.eval.metrics.exact_match`."""

import pytest

from ajolopy.eval.metrics import MetricsConfigError, exact_match
from ajolopy.eval.results import EvalOutput


def _eval_output(text: str) -> EvalOutput:
    return EvalOutput(text=text, latency_ms=1.0, cost_usd=None, trace_id=None, raw=text)


def test_equal_strings_match() -> None:
    assert exact_match("hello", "hello") == 1.0


def test_different_strings_do_not_match() -> None:
    assert exact_match("hello", "world") == 0.0


def test_whitespace_is_stripped_both_sides() -> None:
    assert exact_match("  hello  ", "hello") == 1.0
    assert exact_match("hello", "  hello\n") == 1.0


def test_case_sensitive_by_default() -> None:
    assert exact_match("Hello", "hello") == 0.0


def test_case_insensitive_kwarg() -> None:
    assert exact_match("Hello", "hello", case_insensitive=True) == 1.0
    assert exact_match("WORLD", "world", case_insensitive=True) == 1.0


def test_accepts_eval_output_input() -> None:
    assert exact_match(_eval_output("hello"), "hello") == 1.0


def test_expected_coerced_via_str() -> None:
    assert exact_match("42", 42) == 1.0


def test_invalid_output_type_raises() -> None:
    with pytest.raises(MetricsConfigError, match="exact_match requires str or EvalOutput"):
        exact_match(42, "42")
