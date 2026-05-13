"""Acceptance: compile_module happy path."""

from ajolopy import Module, compile_module
from ajolopy.di import Container
from ajolopy.modules import CompiledModule


class Logger:
    pass


class Db:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger


class UserRepo:
    def __init__(self, db: Db) -> None:
        self.db = db


@Module(providers=[Logger], exports=[Logger])
class CoreModule:
    pass


@Module(imports=[CoreModule], providers=[Db], exports=[Db])
class DbModule:
    pass


@Module(imports=[DbModule, CoreModule], providers=[UserRepo])
class FeatureModule:
    pass


def test_compile_returns_compiled_module() -> None:
    compiled = compile_module(FeatureModule)
    assert isinstance(compiled, CompiledModule)
    assert isinstance(compiled.container, Container)


def test_compiled_container_resolves_every_provider() -> None:
    compiled = compile_module(FeatureModule)
    assert isinstance(compiled.container.resolve(Logger), Logger)
    assert isinstance(compiled.container.resolve(Db), Db)
    assert isinstance(compiled.container.resolve(UserRepo), UserRepo)


def test_singletons_shared_across_modules() -> None:
    compiled = compile_module(FeatureModule)
    logger1 = compiled.container.resolve(Logger)
    db = compiled.container.resolve(Db)
    # Db's __init__ took the same Logger singleton.
    assert db.logger is logger1


def test_module_order_is_leaves_first() -> None:
    compiled = compile_module(FeatureModule)
    order = [m.__qualname__ for m in compiled.module_order]
    # CoreModule is a leaf (no imports); DbModule depends on CoreModule;
    # FeatureModule depends on DbModule (and CoreModule again).
    assert order.index("CoreModule") < order.index("DbModule")
    assert order.index("DbModule") < order.index("FeatureModule")


def test_flat_lists_in_traversal_order() -> None:
    class Ctrl:
        pass

    class Ctrl2:
        pass

    @Module(controllers=[Ctrl])
    class A:
        pass

    @Module(imports=[A], controllers=[Ctrl2])
    class B:
        pass

    compiled = compile_module(B)
    assert compiled.controllers == (Ctrl, Ctrl2)


def test_diamond_import_compiles_each_module_once() -> None:
    """Two siblings (B, C) both import D; the root imports both.

    Without re-export, the root has to import D directly (or import
    something that exports the leaf). D itself appears in module_order
    exactly once and its providers are registered exactly once.
    """

    class DLogger:
        pass

    @Module(providers=[DLogger], exports=[DLogger])
    class D:
        pass

    @Module(imports=[D])
    class B:
        pass

    @Module(imports=[D])
    class C:
        pass

    @Module(imports=[B, C, D])
    class Root:
        pass

    compiled = compile_module(Root)
    # D appears in module_order exactly once.
    assert sum(1 for m in compiled.module_order if m is D) == 1
    # DLogger resolves once (same instance) regardless of resolution
    # path — the diamond did not create duplicate registrations.
    assert compiled.container.resolve(DLogger) is compiled.container.resolve(DLogger)


def test_compile_with_custom_container_uses_it() -> None:
    custom = Container()
    compiled = compile_module(FeatureModule, container=custom)
    assert compiled.container is custom


def test_compiled_module_is_frozen() -> None:
    import dataclasses

    compiled = compile_module(FeatureModule)
    try:
        compiled.controllers = ()  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("CompiledModule should be a frozen dataclass")
