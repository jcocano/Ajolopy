"""Tests for the :mod:`ajolopy.eval` public surface."""

import ajolopy
import ajolopy.eval as eval_pkg
from ajolopy.eval import (
    Case,
    Dataset,
    DatasetError,
    DatasetFileError,
    DatasetSchemaError,
    JSONLDataset,
    resolve_dataset,
)


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


def test_imported_symbols_are_the_real_objects() -> None:
    assert Case is eval_pkg.Case
    assert Dataset is eval_pkg.Dataset
    assert DatasetError is eval_pkg.DatasetError
    assert DatasetFileError is eval_pkg.DatasetFileError
    assert DatasetSchemaError is eval_pkg.DatasetSchemaError
    assert JSONLDataset is eval_pkg.JSONLDataset
    assert resolve_dataset is eval_pkg.resolve_dataset


def test_error_hierarchy() -> None:
    assert issubclass(DatasetFileError, DatasetError)
    assert issubclass(DatasetSchemaError, DatasetError)
    assert issubclass(DatasetError, Exception)


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
