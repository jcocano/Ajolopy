"""Tests for the :class:`Case` dataclass."""

import dataclasses

import pytest

from ajolopy.eval import Case


def test_case_constructs_with_mappings() -> None:
    case = Case(input={"x": 1}, expected={"y": 2})
    assert case.input == {"x": 1}
    assert case.expected == {"y": 2}


def test_case_is_frozen() -> None:
    case = Case(input={"x": 1}, expected={"y": 2})
    with pytest.raises(dataclasses.FrozenInstanceError):
        case.input = {"x": 999}  # type: ignore[misc]


def test_case_has_slots_and_no_dict() -> None:
    assert hasattr(Case, "__slots__")
    assert "__dict__" not in Case.__slots__
    case = Case(input={"x": 1}, expected={"y": 2})
    # __slots__ removes per-instance __dict__ — confirm at runtime too.
    assert not hasattr(case, "__dict__")


def test_two_equal_cases_compare_equal() -> None:
    a = Case(input={"x": 1}, expected={"y": 2})
    b = Case(input={"x": 1}, expected={"y": 2})
    assert a == b


def test_unequal_cases_compare_unequal() -> None:
    a = Case(input={"x": 1}, expected={"y": 2})
    b = Case(input={"x": 1}, expected={"y": 999})
    assert a != b
