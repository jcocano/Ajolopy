"""Acceptance: duplicate provider detection + intra-module dedup."""

import pytest

from ajolopy import Module, compile_module
from ajolopy.modules import DuplicateProviderError


class Foo:
    pass


class Ctrl:
    pass


def test_two_modules_with_same_provider_raises() -> None:
    @Module(providers=[Foo])
    class A:
        pass

    @Module(imports=[A], providers=[Foo])
    class B:
        pass

    with pytest.raises(DuplicateProviderError) as info:
        compile_module(B)
    msg = str(info.value)
    assert "Foo" in msg
    assert "A" in msg
    assert "B" in msg


def test_global_module_provider_collides_with_local() -> None:
    """No 'global wins' shortcut — both raise."""

    @Module(global_=True, providers=[Foo], exports=[Foo])
    class GlobalCfg:
        pass

    @Module(providers=[Foo])
    class Feature:
        pass

    @Module(imports=[GlobalCfg, Feature])
    class Root:
        pass

    with pytest.raises(DuplicateProviderError, match="Foo"):
        compile_module(Root)


def test_provider_in_providers_and_controllers_same_module_deduped() -> None:
    """A class in both providers= and controllers= of the same module
    is registered exactly once and appears in controllers list."""

    @Module(providers=[Ctrl], controllers=[Ctrl])
    class M:
        pass

    compiled = compile_module(M)
    assert compiled.controllers == (Ctrl,)
    # Container resolves Ctrl successfully (one registration).
    instance = compiled.container.resolve(Ctrl)
    assert isinstance(instance, Ctrl)


def test_overlap_across_ai_lists_same_module_deduped() -> None:
    """A class in agents= AND workflows= of the same module is OK."""

    class Agent:
        pass

    @Module(agents=[Agent], workflows=[Agent])
    class M:
        pass

    compiled = compile_module(M)
    # Agent appears in agents (first traversal), not duplicated in workflows.
    assert compiled.agents == (Agent,)
    assert compiled.workflows == ()


def test_prepopulated_container_collision_raises() -> None:
    from ajolopy.di import Container

    @Module(providers=[Foo])
    class M:
        pass

    container = Container()
    container.register(Foo)
    with pytest.raises(DuplicateProviderError, match="Pre-populated"):
        compile_module(M, container=container)


def test_prepopulated_container_no_collision_is_fine() -> None:
    """A pre-populated container with an unrelated token does not block compile."""
    from ajolopy.di import Container

    class Unrelated:
        pass

    @Module(providers=[Foo])
    class M:
        pass

    container = Container()
    container.register(Unrelated)
    compiled = compile_module(M, container=container)
    # Both tokens resolve.
    assert isinstance(compiled.container.resolve(Foo), Foo)
    assert isinstance(compiled.container.resolve(Unrelated), Unrelated)
