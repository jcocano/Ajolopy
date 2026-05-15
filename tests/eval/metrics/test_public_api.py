"""Tests for the public surface of :mod:`ajolopy.eval.metrics`."""

import ajolopy.eval.metrics as metrics_pkg


def test_public_re_exports() -> None:
    """The seven helpers + JudgeCache + the three error types import cleanly.

    The seven documented helpers + ``JudgeCache`` + the three error
    types must all be reachable as attributes of
    :mod:`ajolopy.eval.metrics`. Attribute access (not a separate
    ``from`` import) avoids CodeQL's "module imported with both
    'import' and 'import from'" check.
    """
    expected_names = {
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
    for name in expected_names:
        assert hasattr(metrics_pkg, name), f"missing public attr {name!r}"
        assert getattr(metrics_pkg, name) is getattr(metrics_pkg, name)


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
