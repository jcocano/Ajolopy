"""Tests for :func:`ajolopy.eval.metrics.intent_match`."""

import pytest

from ajolopy.eval.metrics import MetricsConfigError, intent_match
from ajolopy.eval.results import EvalOutput


def _eval_output(text: str) -> EvalOutput:
    return EvalOutput(text=text, latency_ms=1.0, cost_usd=None, trace_id=None, raw=text)


def test_substring_match_returns_one() -> None:
    assert intent_match(_eval_output("this is an order_status check"), "order_status") == 1.0


def test_no_match_returns_zero() -> None:
    assert intent_match(_eval_output("hello"), "order_status") == 0.0


def test_case_insensitive_by_default() -> None:
    assert intent_match(_eval_output("ORDER_STATUS request"), "order_status") == 1.0
    assert intent_match(_eval_output("order_status request"), "ORDER_STATUS") == 1.0


def test_any_of_match_with_list_intent() -> None:
    assert (
        intent_match(_eval_output("user asked cancellation"), ["order_status", "cancellation"])
        == 1.0
    )


def test_any_of_no_match() -> None:
    assert intent_match(_eval_output("hello"), ["order_status", "cancellation"]) == 0.0


def test_exact_mode_whole_string() -> None:
    assert intent_match(_eval_output("ORDER_STATUS"), "order_status", mode="exact") == 1.0


def test_exact_mode_substring_does_not_match() -> None:
    assert intent_match(_eval_output("this is order_status"), "order_status", mode="exact") == 0.0


def test_empty_intent_list_raises() -> None:
    with pytest.raises(MetricsConfigError, match="intent_match: needles is empty"):
        intent_match(_eval_output("hello"), [])


def test_accepts_plain_string() -> None:
    # The coercion rule (str passes through) means a plain string is fine.
    assert intent_match("this is an order_status check", "order_status") == 1.0
