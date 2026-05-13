"""Transient-scope semantics + the singleton-freezes-transient rule."""

from ajolopy.di import Container


class _IdGen:
    pass


class _Singleton:
    def __init__(self, ids: _IdGen) -> None:
        self.ids = ids


def test_transient_yields_new_instance_each_resolve() -> None:
    container = Container()
    container.register(_IdGen, scope="transient")
    assert container.resolve(_IdGen) is not container.resolve(_IdGen)


def test_singleton_freezes_its_transient_dependency() -> None:
    """A transient dep injected into a singleton is captured at build time.

    The framework's behaviour is documented: when the singleton itself
    is resolved a second time, it still holds the same transient
    instance it captured originally.
    """
    container = Container()
    container.register(_IdGen, scope="transient")
    container.register(_Singleton)
    first = container.resolve(_Singleton)
    second = container.resolve(_Singleton)
    assert first is second
    assert first.ids is second.ids
