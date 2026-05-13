"""Composition rules with :class:`Container` and request / transient scopes."""

import pytest

from ajolopy.di import Container
from ajolopy.lifecycle import LifecycleManager


@pytest.mark.asyncio
async def test_request_and_transient_scoped_instances_are_not_walked() -> None:
    """Only singletons appear in ``iter_singletons`` — request / transient don't.

    Lifecycle hooks should fire exclusively on cached singletons; if
    they reached transients we would re-instantiate the dependency on
    every walk, which is incoherent.
    """
    init_log: list[str] = []
    shutdown_log: list[str] = []

    class SingletonSvc:
        async def on_module_init(self) -> None:
            init_log.append("singleton-init")

        async def on_app_shutdown(self) -> None:
            shutdown_log.append("singleton-shutdown")

    class TransientSvc:
        async def on_module_init(self) -> None:
            init_log.append("transient-init")

        async def on_app_shutdown(self) -> None:
            shutdown_log.append("transient-shutdown")

    class RequestSvc:
        async def on_module_init(self) -> None:
            init_log.append("request-init")

    container = Container()
    container.register(SingletonSvc)
    container.register(TransientSvc, scope="transient")
    container.register(RequestSvc, scope="request")
    container.resolve(SingletonSvc)
    # Resolve a transient — it gets created but not cached, so
    # iter_singletons must not pick it up.
    container.resolve(TransientSvc)
    with container.request_scope():
        container.resolve(RequestSvc)
    # The request scope is exited; RequestSvc is gone.

    manager = LifecycleManager(container)
    await manager.bootstrap()
    await manager.shutdown()

    assert init_log == ["singleton-init"]
    assert shutdown_log == ["singleton-shutdown"]


@pytest.mark.asyncio
async def test_singleton_resolved_after_bootstrap_is_not_retroactively_wired() -> None:
    """A late-resolved singleton stays cold — no retroactive hook fire.

    Pins the "no second bootstrap" semantics so future code does not
    silently grow them. AJ-14 will call ``bootstrap()`` exactly once.
    """
    log: list[str] = []

    class Eager:
        async def on_module_init(self) -> None:
            log.append("eager")

    class Late:
        async def on_module_init(self) -> None:
            log.append("late")

    container = Container()
    container.register(Eager)
    container.register(Late)
    container.resolve(Eager)

    await LifecycleManager(container).bootstrap()
    assert log == ["eager"]

    # Resolving Late after bootstrap caches it but no hook fires.
    container.resolve(Late)
    assert log == ["eager"]


@pytest.mark.asyncio
async def test_two_managers_over_same_container_fire_hooks_twice() -> None:
    """Documented but unusual: bootstrap is per-manager, not per-container.

    Pins the behaviour so a future refactor doesn't quietly add
    de-duplication. AJ-14's bootstrap is guaranteed once-per-app.
    """
    log: list[str] = []

    class Svc:
        async def on_module_init(self) -> None:
            log.append("init")

    container = Container()
    container.register(Svc)
    container.resolve(Svc)

    await LifecycleManager(container).bootstrap()
    await LifecycleManager(container).bootstrap()
    assert log == ["init", "init"]
