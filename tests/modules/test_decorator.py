"""Acceptance: decorator metadata stamping + declarative validation."""

import dataclasses

import pytest

from ajolopy import Module
from ajolopy.modules import ForwardRef, ModuleConfigError, ModuleMetadata, forwardRef


class _Provider:
    pass


def test_returns_class_unchanged() -> None:
    @Module(providers=[_Provider])
    class M:
        sentinel = "kept"

    assert M.sentinel == "kept"


def test_metadata_attribute_present_and_typed() -> None:
    @Module(providers=[_Provider])
    class M:
        pass

    assert isinstance(M._ajolopy_module, ModuleMetadata)
    assert M._ajolopy_module.providers == (_Provider,)


def test_empty_kwargs_default_to_empty_tuples_not_shared_lists() -> None:
    @Module()
    class A:
        pass

    @Module()
    class B:
        pass

    assert A._ajolopy_module.providers == ()
    assert A._ajolopy_module.imports == ()
    assert A._ajolopy_module.exports == ()
    # Tuples, not the same shared list instance.
    assert A._ajolopy_module.providers is not B._ajolopy_module.providers or (
        A._ajolopy_module.providers == () == B._ajolopy_module.providers
    )


def test_global_defaults_to_false() -> None:
    @Module()
    class M:
        pass

    assert M._ajolopy_module.global_ is False


def test_global_true_is_stamped() -> None:
    @Module(global_=True)
    class M:
        pass

    assert M._ajolopy_module.global_ is True


def test_exporting_non_provider_raises_at_decoration_time() -> None:
    class NotAProvider:
        pass

    with pytest.raises(ModuleConfigError, match="NotAProvider"):

        @Module(providers=[], exports=[NotAProvider])
        class M:
            pass


def test_imports_with_non_module_does_not_raise_at_decoration_time() -> None:
    class NotAModule:
        pass

    # Compile-time error (deferred), not decoration-time.
    @Module(imports=[NotAModule])
    class M:
        pass

    assert M._ajolopy_module.imports == (NotAModule,)


def test_providers_with_none_raises() -> None:
    with pytest.raises(ModuleConfigError, match="providers"):

        @Module(providers=[None])  # type: ignore[list-item]
        class M:
            pass


def test_providers_with_non_type_raises() -> None:
    with pytest.raises(ModuleConfigError, match="providers"):

        @Module(providers=["not a type"])  # type: ignore[list-item]
        class M:
            pass


def test_controllers_with_non_type_raises() -> None:
    with pytest.raises(ModuleConfigError, match="controllers"):

        @Module(controllers=[42])  # type: ignore[list-item]
        class M:
            pass


def test_imports_accepts_forward_ref_and_type() -> None:
    @Module()
    class Other:
        pass

    @Module(imports=[Other, forwardRef(lambda: Other)])
    class M:
        pass

    assert isinstance(M._ajolopy_module.imports[1], ForwardRef)


def test_imports_with_non_type_non_forwardref_raises() -> None:
    with pytest.raises(ModuleConfigError, match="imports"):

        @Module(imports=["not a module"])  # type: ignore[list-item]
        class M:
            pass


def test_re_decoration_raises() -> None:
    @Module(providers=[_Provider])
    class M:
        pass

    with pytest.raises(ModuleConfigError, match="already decorated"):
        Module()(M)


def test_metadata_not_inherited_by_subclasses() -> None:
    @Module(providers=[_Provider])
    class Parent:
        pass

    class Child(Parent):  # pyright: ignore[reportUntypedBaseClass]
        pass

    # Parent has metadata; Child does not (because we check __dict__).
    assert "_ajolopy_module" in Parent.__dict__
    assert "_ajolopy_module" not in Child.__dict__


def test_metadata_is_frozen_dataclass() -> None:
    @Module(providers=[_Provider])
    class M:
        pass

    with pytest.raises(dataclasses.FrozenInstanceError):
        M._ajolopy_module.providers = ()


def test_global_non_bool_raises() -> None:
    with pytest.raises(ModuleConfigError, match="global_"):

        @Module(global_="yes")  # type: ignore[arg-type]
        class M:
            pass


def test_kwarg_not_a_list_raises() -> None:
    with pytest.raises(ModuleConfigError, match="must be a list"):

        @Module(providers=(_Provider,))  # type: ignore[arg-type]
        class M:
            pass
