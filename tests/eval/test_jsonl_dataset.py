"""Tests for :class:`JSONLDataset` — happy and error paths."""

import asyncio
import os
from pathlib import Path

import pytest

from ajolopy.eval import (
    Case,
    DatasetFileError,
    DatasetSchemaError,
    JSONLDataset,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_loads_three_cases_in_order() -> None:
    ds = JSONLDataset(FIXTURES / "support.jsonl")
    cases = list(ds)
    assert len(cases) == 3
    assert cases[0] == Case(
        input={"message": "where is my order?"},
        expected={"intent": "order_status"},
    )
    assert cases[1] == Case(
        input={"message": "cancel my order"},
        expected={"intent": "cancellation"},
    )
    assert cases[2] == Case(
        input={"message": "hello"},
        expected={"intent": "greeting"},
    )


def test_async_iteration_matches_sync_iteration() -> None:
    ds = JSONLDataset(FIXTURES / "support.jsonl")

    async def collect() -> list[Case]:
        return [c async for c in ds]

    sync_cases = list(ds)
    async_cases = asyncio.run(collect())
    assert sync_cases == async_cases


def test_len_returns_case_count() -> None:
    ds = JSONLDataset(FIXTURES / "support.jsonl")
    assert len(ds) == 3


def test_path_property_is_resolved_absolute() -> None:
    ds = JSONLDataset(FIXTURES / "support.jsonl")
    assert ds.path.is_absolute()
    assert ds.path == (FIXTURES / "support.jsonl").resolve()


def test_extra_keys_per_case_are_silently_ignored() -> None:
    ds = JSONLDataset(FIXTURES / "extra_keys.jsonl")
    cases = list(ds)
    assert cases == [Case(input={"message": "ping"}, expected={"intent": "ping"})]


def test_blank_lines_are_skipped() -> None:
    ds = JSONLDataset(FIXTURES / "with_blanks.jsonl")
    cases = list(ds)
    assert cases == [
        Case(input={"x": 1}, expected={"y": 2}),
        Case(input={"x": 3}, expected={"y": 4}),
        Case(input={"x": 5}, expected={"y": 6}),
    ]


def test_whitespace_only_lines_are_skipped_and_counted_for_diagnostics(
    tmp_path: Path,
) -> None:
    # Line 1: valid, line 2: whitespace-only, line 3: malformed JSON.
    # The malformed-JSON diagnostic must point at line 3, not line 2,
    # because blank/whitespace lines advance the counter.
    path = tmp_path / "ws.jsonl"
    path.write_text(
        '{"input": {"x": 1}, "expected": {"y": 2}}\n   \n{bad}\n',
        encoding="utf-8",
    )
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(path)
    err = excinfo.value
    assert err.line == 3
    assert "line 3" in str(err)


def test_trailing_newline_at_eof_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "trailing.jsonl"
    path.write_text('{"input": {"x": 1}, "expected": {"y": 2}}\n', encoding="utf-8")
    ds = JSONLDataset(path)
    assert len(ds) == 1


def test_relative_path_resolves_against_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = tmp_path / "evals"
    sub.mkdir()
    path = sub / "rel.jsonl"
    path.write_text('{"input": {"x": 1}, "expected": {"y": 2}}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    ds = JSONLDataset("evals/rel.jsonl")
    assert ds.path == path.resolve()


def test_absolute_path_passes_through(tmp_path: Path) -> None:
    path = tmp_path / "abs.jsonl"
    path.write_text('{"input": {"x": 1}, "expected": {"y": 2}}\n', encoding="utf-8")
    ds = JSONLDataset(str(path.resolve()))
    assert ds.path == path.resolve()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_non_existent_file_raises_file_error(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(DatasetFileError) as excinfo:
        JSONLDataset(missing)
    assert str(missing.resolve()) in str(excinfo.value)


def test_directory_path_raises_file_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetFileError):
        JSONLDataset(tmp_path)


def test_empty_file_raises_schema_error_with_line_none(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(path)
    assert excinfo.value.line is None
    assert "dataset is empty" in str(excinfo.value)


def test_file_with_only_blank_lines_raises_dataset_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "blanks_only.jsonl"
    path.write_text("\n\n   \n\t\n", encoding="utf-8")
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(path)
    assert excinfo.value.line is None
    assert "dataset is empty" in str(excinfo.value)


def test_malformed_json_raises_with_line_number() -> None:
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(FIXTURES / "bad_json.jsonl")
    err = excinfo.value
    assert err.line == 2
    assert "line 2" in str(err)
    assert "invalid JSON" in str(err)


def test_top_level_array_raises_with_line_number() -> None:
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(FIXTURES / "top_level_array.jsonl")
    err = excinfo.value
    assert err.line == 1
    assert str(err) == "line 1: case must be a JSON object"


def test_missing_input_key_raises_with_line_number() -> None:
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(FIXTURES / "missing_input.jsonl")
    err = excinfo.value
    assert err.line == 3
    assert "line 3" in str(err)
    assert "'input'" in str(err)
    assert "missing required key" in str(err)


def test_missing_expected_key_raises_with_line_number(tmp_path: Path) -> None:
    path = tmp_path / "missing_expected.jsonl"
    path.write_text('{"input": {"x": 1}}\n', encoding="utf-8")
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(path)
    err = excinfo.value
    assert err.line == 1
    assert "'expected'" in str(err)


def test_input_string_raises_with_descriptive_message() -> None:
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(FIXTURES / "input_string.jsonl")
    err = excinfo.value
    assert err.line == 1
    assert "'input'" in str(err)
    assert "must be a JSON object" in str(err)


def test_expected_not_an_object_raises(tmp_path: Path) -> None:
    path = tmp_path / "expected_string.jsonl"
    path.write_text('{"input": {"x": 1}, "expected": "nope"}\n', encoding="utf-8")
    with pytest.raises(DatasetSchemaError) as excinfo:
        JSONLDataset(path)
    err = excinfo.value
    assert err.line == 1
    assert "'expected'" in str(err)
    assert "must be a JSON object" in str(err)


def test_unreadable_file_raises_file_error(tmp_path: Path) -> None:
    path = tmp_path / "locked.jsonl"
    path.write_text('{"input": {"x": 1}, "expected": {"y": 2}}\n', encoding="utf-8")
    path.chmod(0o000)
    try:
        # Root bypasses chmod 000 — skip when the test isn't running unprivileged.
        if os.access(path, os.R_OK):
            pytest.skip("running as root; permission check cannot be exercised")
        with pytest.raises(DatasetFileError):
            JSONLDataset(path)
    finally:
        path.chmod(0o600)
