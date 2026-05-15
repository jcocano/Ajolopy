"""Tests for :mod:`ajolopy.cli.deploy.registry`."""

from collections.abc import Iterable
from typing import ClassVar

import pytest

from ajolopy.cli.deploy import DeployContext, DeployResult
from ajolopy.cli.deploy.errors import DeployTargetNotFoundError
from ajolopy.cli.deploy.registry import (
    _clear_registry_for_tests,
    get_target,
    list_targets,
    register_target,
)


class _StubTarget:
    """Minimal Protocol-conforming target for registry tests."""

    name: ClassVar[str] = "stub"
    description: ClassVar[str] = "stub"

    def prepare(self, ctx: DeployContext) -> DeployResult:
        del ctx
        return DeployResult(files={})

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        del ctx, result
        return ()


@pytest.fixture
def isolated_registry() -> Iterable[None]:
    """Wipe the registry before AND after each test.

    The package import auto-registers five targets; tests that exercise
    the registry surface need to start from an empty slate. Restoring
    the defaults after the test is handled by re-importing the
    package, but each test asserts only on what it registered, so the
    re-import is unnecessary unless other tests depend on the defaults
    being live in the same process.
    """
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()
    # Re-register the default surface so unrelated tests that import
    # ``ajolopy.cli.deploy`` later still see the v0.1 targets.
    import ajolopy.cli.deploy as _pkg

    _pkg.register_target(_pkg.DockerTarget())
    _pkg.register_target(_pkg.FlyStub())
    _pkg.register_target(_pkg.RailwayStub())
    _pkg.register_target(_pkg.RenderStub())
    _pkg.register_target(_pkg.VercelStub())


def test_register_target_inserts_in_order(isolated_registry: None) -> None:
    del isolated_registry

    class FirstTarget(_StubTarget):
        name: ClassVar[str] = "first"

    class SecondTarget(_StubTarget):
        name: ClassVar[str] = "second"

    first = FirstTarget()
    second = SecondTarget()
    register_target(first)
    register_target(second)

    assert list_targets() == [first, second]


def test_register_target_last_write_wins(isolated_registry: None) -> None:
    del isolated_registry

    class FirstImpl(_StubTarget):
        name: ClassVar[str] = "shared"
        description: ClassVar[str] = "first"

    class SecondImpl(_StubTarget):
        name: ClassVar[str] = "shared"
        description: ClassVar[str] = "second"

    register_target(FirstImpl())
    replacement = SecondImpl()
    register_target(replacement)

    assert get_target("shared") is replacement
    assert list_targets() == [replacement]


def test_get_target_returns_registered_instance(isolated_registry: None) -> None:
    del isolated_registry
    instance = _StubTarget()
    register_target(instance)
    assert get_target("stub") is instance


def test_get_target_unknown_raises_with_known_names(isolated_registry: None) -> None:
    del isolated_registry

    class FirstTarget(_StubTarget):
        name: ClassVar[str] = "alpha"

    class SecondTarget(_StubTarget):
        name: ClassVar[str] = "beta"

    register_target(FirstTarget())
    register_target(SecondTarget())

    with pytest.raises(DeployTargetNotFoundError) as exc:
        get_target("missing")
    message = str(exc.value)
    assert "missing" in message
    assert "alpha" in message
    assert "beta" in message


def test_get_target_unknown_lists_none_when_empty(isolated_registry: None) -> None:
    del isolated_registry
    with pytest.raises(DeployTargetNotFoundError) as exc:
        get_target("anything")
    assert "(none)" in str(exc.value)


def test_default_registry_lists_five_targets() -> None:
    """Smoke check: importing the package registers all v0.1 targets."""
    names = [t.name for t in list_targets()]
    assert names == ["docker", "fly", "railway", "render", "vercel"]
