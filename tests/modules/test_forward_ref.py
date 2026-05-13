"""Acceptance: forwardRef behaviour."""

import pytest

from ajolopy import Module, forwardRef
from ajolopy.modules import ForwardRef, UnresolvedForwardRefError


@Module()
class _RealModule:
    pass


def test_forward_ref_returns_sentinel() -> None:
    ref = forwardRef(lambda: _RealModule)
    assert isinstance(ref, ForwardRef)


def test_resolve_returns_module_class() -> None:
    ref = forwardRef(lambda: _RealModule)
    assert ref.resolve() is _RealModule


def test_resolve_non_module_raises() -> None:
    class NotDecorated:
        pass

    ref = forwardRef(lambda: NotDecorated)
    with pytest.raises(UnresolvedForwardRefError, match="not decorated"):
        ref.resolve()


def test_resolve_non_class_raises() -> None:
    ref = forwardRef(lambda: "not a class")  # type: ignore[arg-type, return-value]
    with pytest.raises(UnresolvedForwardRefError, match="expected a class"):
        ref.resolve()


def test_resolve_thunk_raises_propagates_typed() -> None:
    def thunk() -> type:
        raise RuntimeError("kaboom")

    ref = forwardRef(thunk)
    with pytest.raises(UnresolvedForwardRefError, match="kaboom") as info:
        ref.resolve()
    assert isinstance(info.value.__cause__, RuntimeError)


def test_chained_forward_ref_raises() -> None:
    inner = forwardRef(lambda: _RealModule)
    outer = forwardRef(lambda: inner)  # type: ignore[arg-type, return-value]
    with pytest.raises(UnresolvedForwardRefError, match="chained"):
        outer.resolve()
