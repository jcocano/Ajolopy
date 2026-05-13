"""Acceptance: error sanity cases."""

import pytest

from ajolopy import Module, compile_module
from ajolopy.modules import NotAModuleError


class NotAModule:
    pass


def test_compile_non_module_raises() -> None:
    with pytest.raises(NotAModuleError, match="NotAModule"):
        compile_module(NotAModule)


def test_compile_empty_module_returns_empty_compiled() -> None:
    @Module()
    class Empty:
        pass

    compiled = compile_module(Empty)
    assert compiled.controllers == ()
    assert compiled.agents == ()
    assert compiled.workflows == ()
    assert compiled.evals == ()
    assert compiled.module_order == (Empty,)


def test_import_non_module_raises_at_compile_time() -> None:
    @Module(imports=[NotAModule])
    class M:
        pass

    with pytest.raises(NotAModuleError, match="NotAModule"):
        compile_module(M)


def test_compile_with_non_class_root_raises() -> None:
    with pytest.raises(NotAModuleError):
        compile_module("AppModule")  # type: ignore[arg-type]
