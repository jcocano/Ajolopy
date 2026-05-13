"""Acceptance: visibility, globals, re-exporting forbidden."""

import pytest

from ajolopy import Module, compile_module
from ajolopy.modules import ModuleConfigError, ModuleVisibilityError


class FooService:
    pass


class BarService:
    pass


@Module(providers=[FooService], exports=[FooService])
class ExporterModule:
    pass


@Module(providers=[FooService, BarService], exports=[FooService])
class PartialExportModule:
    pass


def test_imported_module_exports_are_visible() -> None:
    class Consumer:
        def __init__(self, foo: FooService) -> None:
            self.foo = foo

    @Module(imports=[ExporterModule], providers=[Consumer])
    class App:
        pass

    compiled = compile_module(App)
    consumer = compiled.container.resolve(Consumer)
    assert isinstance(consumer.foo, FooService)


def test_imported_module_non_exports_are_not_visible() -> None:
    class Consumer:
        def __init__(self, bar: BarService) -> None:
            self.bar = bar

    @Module(imports=[PartialExportModule], providers=[Consumer])
    class App:
        pass

    with pytest.raises(ModuleVisibilityError, match="BarService"):
        compile_module(App)


def test_re_exporting_imported_module_is_decoration_time_error() -> None:
    with pytest.raises(ModuleConfigError, match="exports"):

        @Module(imports=[ExporterModule], exports=[ExporterModule])
        class Bad:
            pass


def test_global_module_visible_without_explicit_import() -> None:
    class ConfigService:
        pass

    @Module(global_=True, providers=[ConfigService], exports=[ConfigService])
    class ConfigModule:
        pass

    class Consumer:
        def __init__(self, cfg: ConfigService) -> None:
            self.cfg = cfg

    @Module(providers=[Consumer])
    class FeatureModule:
        pass

    @Module(imports=[ConfigModule, FeatureModule])
    class Root:
        pass

    compiled = compile_module(Root)
    consumer = compiled.container.resolve(Consumer)
    assert isinstance(consumer.cfg, ConfigService)


def test_global_non_exports_stay_private() -> None:
    class Public:
        pass

    class Private:
        pass

    @Module(global_=True, providers=[Public, Private], exports=[Public])
    class ConfigModule:
        pass

    class Consumer:
        def __init__(self, p: Private) -> None:
            self.p = p

    @Module(providers=[Consumer])
    class FeatureModule:
        pass

    @Module(imports=[ConfigModule, FeatureModule])
    class Root:
        pass

    with pytest.raises(ModuleVisibilityError, match="Private"):
        compile_module(Root)


def test_two_global_modules_dont_share_internals() -> None:
    class AExported:
        pass

    class APrivate:
        pass

    class BExported:
        pass

    class BPrivate:
        pass

    @Module(global_=True, providers=[AExported, APrivate], exports=[AExported])
    class GlobalA:
        pass

    @Module(global_=True, providers=[BExported, BPrivate], exports=[BExported])
    class GlobalB:
        pass

    # A consumer asking for B's private should fail visibility.
    class Consumer:
        def __init__(self, p: BPrivate) -> None:
            self.p = p

    @Module(providers=[Consumer])
    class Feature:
        pass

    @Module(imports=[GlobalA, GlobalB, Feature])
    class Root:
        pass

    with pytest.raises(ModuleVisibilityError, match="BPrivate"):
        compile_module(Root)
