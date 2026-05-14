"""Tests for the :class:`Dataset` ABC contract."""

from collections.abc import AsyncIterator, Iterator
from typing import override

import pytest

from ajolopy.eval import Case, Dataset


def test_dataset_abc_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Dataset()  # type: ignore[abstract]


def test_subclass_with_only_iter_is_still_abstract() -> None:
    class OnlySync(Dataset):
        @override
        def __iter__(self) -> Iterator[Case]:
            return iter(())

    with pytest.raises(TypeError):
        OnlySync()  # type: ignore[abstract]


def test_subclass_with_only_aiter_is_still_abstract() -> None:
    class OnlyAsync(Dataset):
        @override
        async def __aiter__(self) -> AsyncIterator[Case]:
            if False:
                yield Case(input={}, expected={})

    with pytest.raises(TypeError):
        OnlyAsync()  # type: ignore[abstract]


def test_subclass_with_both_is_instantiable_and_iterable() -> None:
    cases = [
        Case(input={"x": 1}, expected={"y": 1}),
        Case(input={"x": 2}, expected={"y": 2}),
    ]

    class Both(Dataset):
        @override
        def __iter__(self) -> Iterator[Case]:
            return iter(cases)

        @override
        async def __aiter__(self) -> AsyncIterator[Case]:
            for case in cases:
                yield case

    ds = Both()
    assert list(ds) == cases

    import asyncio

    async def collect() -> list[Case]:
        return [c async for c in ds]

    assert asyncio.run(collect()) == cases
