"""Tests for the :mod:`ajolopy.eval` public surface."""

import ajolopy
import ajolopy.eval as eval_pkg


def test_dataset_layer_names_still_exported() -> None:
    """AJ-25 names continue to be available — AJ-4 layered on top of them."""
    expected = {
        "Case",
        "Dataset",
        "DatasetError",
        "DatasetFileError",
        "DatasetSchemaError",
        "JSONLDataset",
        "resolve_dataset",
    }
    assert expected.issubset(set(eval_pkg.__all__))


def test_eval_layer_names_are_exported() -> None:
    """AJ-4 ships the @Eval / @Metric public surface under ``ajolopy.eval``."""
    expected = {
        "Eval",
        "Metric",
        "EvalRunner",
        "EvalOutput",
        "EvalCaseResult",
        "EvalMetricResult",
        "EvalRun",
        "EvalComparison",
        "MetricDelta",
        "compare_runs",
        "EvalConfigError",
        "EvalRunError",
        "EvalComparisonError",
        "MetricConfigError",
        "MetricRuntimeError",
    }
    assert expected.issubset(set(eval_pkg.__all__))


def test_dataset_error_hierarchy() -> None:
    assert issubclass(eval_pkg.DatasetFileError, eval_pkg.DatasetError)
    assert issubclass(eval_pkg.DatasetSchemaError, eval_pkg.DatasetError)
    assert issubclass(eval_pkg.DatasetError, Exception)


def test_eval_errors_are_exceptions() -> None:
    for err in (
        eval_pkg.EvalConfigError,
        eval_pkg.MetricConfigError,
        eval_pkg.EvalRunError,
        eval_pkg.MetricRuntimeError,
        eval_pkg.EvalComparisonError,
    ):
        assert issubclass(err, Exception)


def test_eval_and_metric_are_top_level() -> None:
    """``Eval`` and ``Metric`` are the only @Eval-layer symbols at top level."""
    assert "Eval" in ajolopy.__all__
    assert "Metric" in ajolopy.__all__
    assert ajolopy.Eval is eval_pkg.Eval
    assert ajolopy.Metric is eval_pkg.Metric


def test_dataset_layer_stays_under_eval_namespace() -> None:
    """AJ-25 names remain scoped under ``ajolopy.eval``; only @Eval/@Metric are top-level."""
    for name in (
        "Case",
        "Dataset",
        "DatasetError",
        "JSONLDataset",
        "resolve_dataset",
        "EvalRunner",
        "EvalRun",
    ):
        assert name not in ajolopy.__all__
