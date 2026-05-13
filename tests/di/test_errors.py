"""Error surface: ProviderNotRegistered, CircularDependency, MissingAnnotation."""

from typing import Annotated

import pytest

from ajolopy.di import (
    CircularDependencyError,
    Container,
    MissingAnnotationError,
    ProviderNotRegisteredError,
)


class _Foo:
    pass


class _A:
    def __init__(self, b: _B) -> None:
        self.b = b


class _B:
    def __init__(self, a: _A) -> None:
        self.a = a


class _NoHint:
    def __init__(self, db) -> None:
        self.db = db


class _Markered:
    def __init__(self, db: Annotated[str, "some-marker"]) -> None:
        self.db = db


class _Unreachable:
    # Quoted on purpose: PEP 649 evaluates annotations lazily via the
    # ``__annotate__`` function so plain ``inspect.signature`` access
    # would fail at class introspection time. Keeping the string makes
    # the eager-eval failure happen inside ``get_type_hints`` — exactly
    # where the container expects it.
    def __init__(self, dep: "DefinedNowhere") -> None:  # type: ignore[name-defined]  # noqa: F821, UP037
        self.dep = dep


def test_resolve_unregistered_raises() -> None:
    container = Container()
    with pytest.raises(ProviderNotRegisteredError, match="_Foo"):
        container.resolve(_Foo)


def test_resolve_unregistered_dependency_names_parent() -> None:
    container = Container()
    container.register(_A)
    # Direct cycle aside, _A.__init__ wants _B which is unregistered.
    container.register(_B)
    # Now both registered — would form a cycle. Drop _B and assert the
    # missing-dep variant.
    container = Container()
    container.register(_A)
    with pytest.raises(ProviderNotRegisteredError, match=r"_B.*_A"):
        container.resolve(_A)


def test_circular_dependency_lists_full_path() -> None:
    container = Container()
    container.register(_A)
    container.register(_B)
    with pytest.raises(CircularDependencyError, match=r"_A.*_B.*_A"):
        container.resolve(_A)


def test_missing_annotation_names_param_and_class() -> None:
    container = Container()
    container.register(_NoHint)
    with pytest.raises(MissingAnnotationError, match=r"_NoHint.*'db'"):
        container.resolve(_NoHint)


def test_annotated_marker_without_concrete_type_raises() -> None:
    container = Container()
    container.register(_Markered)
    with pytest.raises(MissingAnnotationError, match="markers like"):
        container.resolve(_Markered)


def test_unreachable_forward_reference_raises() -> None:
    container = Container()
    container.register(_Unreachable)
    with pytest.raises(MissingAnnotationError, match="unresolvable type annotation"):
        container.resolve(_Unreachable)
