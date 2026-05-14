"""Tests for the :mod:`ajolopy.eval` public surface."""

import ajolopy
import ajolopy.eval as eval_pkg


def test_all_listed_names_are_exported() -> None:
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


def test_error_hierarchy() -> None:
    assert issubclass(eval_pkg.DatasetFileError, eval_pkg.DatasetError)
    assert issubclass(eval_pkg.DatasetSchemaError, eval_pkg.DatasetError)
    assert issubclass(eval_pkg.DatasetError, Exception)


def test_eval_symbols_are_not_top_level() -> None:
    # AJ-4 will decide whether @Eval re-exports anything top-level.
    # AJ-25 ships only under ``ajolopy.eval``.
    for name in (
        "Case",
        "Dataset",
        "DatasetError",
        "JSONLDataset",
        "resolve_dataset",
    ):
        assert name not in ajolopy.__all__
