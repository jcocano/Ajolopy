"""Tests for :func:`ajolopy.eval.metrics.json_match`."""

import pytest

from ajolopy.eval.metrics import MetricsConfigError, json_match
from ajolopy.eval.results import EvalOutput


def _eval_output(text: str) -> EvalOutput:
    return EvalOutput(text=text, latency_ms=1.0, cost_usd=None, trace_id=None, raw=text)


def test_dict_equal() -> None:
    assert json_match('{"a": 1}', {"a": 1}) == 1.0


def test_dict_value_mismatch() -> None:
    assert json_match('{"a": 1}', {"a": 2}) == 0.0


def test_array_equal() -> None:
    assert json_match("[1, 2, 3]", [1, 2, 3]) == 1.0


def test_array_mismatch() -> None:
    assert json_match("[1, 2, 3]", [1, 2]) == 0.0


def test_parse_failure_is_mismatch_not_raise() -> None:
    assert json_match("not json", {"a": 1}) == 0.0


def test_accepts_eval_output() -> None:
    assert json_match(_eval_output('{"a": 1}'), {"a": 1}) == 1.0


def test_partial_kwarg_is_reserved() -> None:
    with pytest.raises(MetricsConfigError, match=r"partial=True is reserved for v0\.2"):
        json_match('{"a": 1}', {"a": 1}, partial=True)


def test_scalar_match() -> None:
    assert json_match("42", 42) == 1.0
    assert json_match("true", True) == 1.0
    assert json_match("null", None) == 1.0


def test_nested_structure() -> None:
    assert json_match('{"a": [1, {"b": 2}]}', {"a": [1, {"b": 2}]}) == 1.0
