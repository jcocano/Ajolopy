"""Acceptance: circular module imports + forwardRef compile-time resolution."""

import pytest

from ajolopy import Module, compile_module, forwardRef
from ajolopy.modules import CircularModuleImportError, UnresolvedForwardRefError


def test_forward_ref_resolves_cycle_at_compile_time() -> None:
    @Module(imports=[forwardRef(lambda: B)])
    class A:
        pass

    @Module(imports=[forwardRef(lambda: A)])
    class B:
        pass

    compiled = compile_module(A)
    assert A in compiled.module_order
    assert B in compiled.module_order


def test_cycle_without_forward_ref_raises() -> None:
    """Two modules that mutually reference each other without forwardRef.

    Constructed via mutation after decoration because Python's decoration
    order precludes building a literal name-cycle in a single pass.
    """

    @Module()
    class A:
        pass

    @Module(imports=[A])
    class B:
        pass

    # Forge a cycle without forwardRef by patching the metadata to point
    # back at B. This is what a typo or a refactor would produce.
    from ajolopy.modules import ModuleMetadata

    A._ajolopy_module = ModuleMetadata(
        imports=(B,),
        providers=(),
        controllers=(),
        agents=(),
        workflows=(),
        evals=(),
        exports=(),
        global_=False,
    )

    with pytest.raises(CircularModuleImportError) as info:
        compile_module(A)
    msg = str(info.value)
    # Cycle path includes both modules.
    assert "A" in msg
    assert "B" in msg
    # Both endpoints of the cycle appear; the path is "X → Y → X".
    assert msg.count("→") >= 2


def test_self_import_raises() -> None:
    """A module that imports itself via forwardRef raises."""

    @Module(imports=[forwardRef(lambda: SelfMod)])
    class SelfMod:
        pass

    with pytest.raises(CircularModuleImportError) as info:
        compile_module(SelfMod)
    msg = str(info.value)
    assert msg.count("SelfMod") >= 2


def test_forward_ref_chain_raises() -> None:
    """forwardRef thunk returning another forwardRef rejected."""

    @Module()
    class Real:
        pass

    inner = forwardRef(lambda: Real)
    outer = forwardRef(lambda: inner)  # type: ignore[arg-type, return-value]

    @Module(imports=[outer])
    class Bad:
        pass

    with pytest.raises(UnresolvedForwardRefError, match="chained"):
        compile_module(Bad)
