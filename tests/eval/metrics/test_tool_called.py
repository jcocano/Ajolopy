"""Tests for :func:`ajolopy.eval.metrics.tool_called`."""

import pytest

from ajolopy.eval.metrics import MetricsConfigError, tool_called
from ajolopy.eval.results import EvalOutput


def _output(*tool_names: str) -> EvalOutput:
    return EvalOutput(
        text="",
        latency_ms=0.0,
        cost_usd=None,
        trace_id=None,
        raw=None,
        tool_calls=tool_names,
    )


def test_single_tool_present() -> None:
    assert tool_called(_output("lookup_order"), "lookup_order") == 1.0


def test_single_tool_absent() -> None:
    assert tool_called(_output("other"), "lookup_order") == 0.0


def test_none_with_empty_tool_calls_returns_one() -> None:
    assert tool_called(_output(), None) == 1.0


def test_none_with_any_tool_returns_zero() -> None:
    assert tool_called(_output("any"), None) == 0.0


def test_all_mode_satisfied() -> None:
    assert tool_called(_output("a", "b"), ["a", "b"], mode="all") == 1.0


def test_all_mode_partial_returns_zero() -> None:
    assert tool_called(_output("a"), ["a", "b"], mode="all") == 0.0


def test_any_mode_default() -> None:
    assert tool_called(_output("a"), ["a", "b"]) == 1.0
    assert tool_called(_output("c"), ["a", "b"]) == 0.0


def test_plain_string_rejected() -> None:
    with pytest.raises(MetricsConfigError, match="tool_called requires an EvalOutput"):
        tool_called("plain string", "lookup_order")


def test_eval_output_default_tool_calls_empty() -> None:
    """Constructing :class:`EvalOutput` without ``tool_calls`` yields ``()``."""
    output = EvalOutput(text="", latency_ms=0.0, cost_usd=None, trace_id=None, raw=None)
    assert output.tool_calls == ()
    assert tool_called(output, None) == 1.0
    assert tool_called(output, "anything") == 0.0
