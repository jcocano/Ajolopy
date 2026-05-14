"""Tests for :func:`resolve_dataset`."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import override

import pytest

from ajolopy.eval import (
    Case,
    Dataset,
    DatasetError,
    JSONLDataset,
    resolve_dataset,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_string_path_returns_jsonl_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = tmp_path / "evals"
    sub.mkdir()
    path = sub / "support.jsonl"
    path.write_text('{"input": {"x": 1}, "expected": {"y": 2}}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    ds = resolve_dataset("evals/support.jsonl")
    assert isinstance(ds, JSONLDataset)
    assert ds.path == path.resolve()


def test_pathlib_path_returns_jsonl_dataset() -> None:
    ds = resolve_dataset(FIXTURES / "support.jsonl")
    assert isinstance(ds, JSONLDataset)


def test_instance_is_returned_verbatim() -> None:
    original = JSONLDataset(FIXTURES / "support.jsonl")
    result = resolve_dataset(original)
    assert result is original


def test_jsonl_dataset_class_raises_with_instance_hint() -> None:
    with pytest.raises(DatasetError) as excinfo:
        resolve_dataset(JSONLDataset)
    assert "instance" in str(excinfo.value).lower()
    assert "JSONLDataset" in str(excinfo.value)


def test_zero_arg_subclass_is_instantiated() -> None:
    cases = [Case(input={"x": 1}, expected={"y": 1})]

    class ZeroArgDataset(Dataset):
        @override
        def __iter__(self) -> Iterator[Case]:
            return iter(cases)

        @override
        async def __aiter__(self) -> AsyncIterator[Case]:
            for case in cases:
                yield case

    ds = resolve_dataset(ZeroArgDataset)
    assert isinstance(ds, ZeroArgDataset)
    assert list(ds) == cases


def test_required_arg_subclass_raises_with_instance_hint() -> None:
    class RequiredArgDataset(Dataset):
        def __init__(self, name: str) -> None:
            self.name = name

        @override
        def __iter__(self) -> Iterator[Case]:
            return iter(())

        @override
        async def __aiter__(self) -> AsyncIterator[Case]:
            if False:
                yield Case(input={}, expected={})

    with pytest.raises(DatasetError) as excinfo:
        resolve_dataset(RequiredArgDataset)
    assert "instance" in str(excinfo.value).lower()
    assert "RequiredArgDataset" in str(excinfo.value)


def test_unsupported_spec_type_raises_with_accepted_forms() -> None:
    with pytest.raises(DatasetError) as excinfo:
        resolve_dataset(42)  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "str" in msg
    assert "PathLike" in msg
    assert "Dataset" in msg
    assert "int" in msg
