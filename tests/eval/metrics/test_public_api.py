"""Tests for the public surface of :mod:`ajolopy.eval.metrics`."""

import ajolopy.eval.metrics as metrics_pkg


def test_public_re_exports() -> None:
    """The seven helpers + JudgeCache + the three error types import cleanly."""
    # The import happens inside :mod:`ajolopy.eval.metrics`; this test
    # asserts that the public attribute lookup matches what the
    # documented import path resolves to. Pyright happily sees these
    # as used because we exercise them after binding.
    from ajolopy.eval.metrics import (
        JudgeCache,
        MetricsConfigError,
        MetricsError,
        MetricsRuntimeError,
        contains,
        exact_match,
        intent_match,
        json_match,
        llm_judge,
        not_contains,
        tool_called,
    )

    assert JudgeCache is metrics_pkg.JudgeCache
    assert MetricsConfigError is metrics_pkg.MetricsConfigError
    assert MetricsError is metrics_pkg.MetricsError
    assert MetricsRuntimeError is metrics_pkg.MetricsRuntimeError
    assert contains is metrics_pkg.contains
    assert exact_match is metrics_pkg.exact_match
    assert intent_match is metrics_pkg.intent_match
    assert json_match is metrics_pkg.json_match
    assert llm_judge is metrics_pkg.llm_judge
    assert not_contains is metrics_pkg.not_contains
    assert tool_called is metrics_pkg.tool_called


def test_all_lists_documented_names() -> None:
    assert set(metrics_pkg.__all__) == {
        "JudgeCache",
        "MetricsConfigError",
        "MetricsError",
        "MetricsRuntimeError",
        "contains",
        "exact_match",
        "intent_match",
        "json_match",
        "llm_judge",
        "not_contains",
        "tool_called",
    }


def test_no_top_level_re_export() -> None:
    """The helpers stay under :mod:`ajolopy.eval.metrics` per the spec.

    The Brief documents ``from ajolopy.eval.metrics import ...``
    consistently; the top-level ``ajolopy`` namespace exposes only
    primitives (``Agent``, ``Tool``, ``Eval``, ...).
    """
    import ajolopy

    assert not hasattr(ajolopy, "exact_match")
    assert not hasattr(ajolopy, "llm_judge")
    assert not hasattr(ajolopy, "tool_called")
