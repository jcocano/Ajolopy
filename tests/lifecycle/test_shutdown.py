"""Shutdown phase — reverse order, resilient to per-instance failures."""

import logging

import pytest

from ajolopy.di import Container
from ajolopy.lifecycle import LifecycleManager


@pytest.mark.asyncio
async def test_shutdown_runs_in_reverse_resolution_order() -> None:
    log: list[str] = []

    class A:
        async def on_app_shutdown(self) -> None:
            log.append("A")

    class B:
        async def on_app_shutdown(self) -> None:
            log.append("B")

    container = Container()
    container.register(A)
    container.register(B)
    container.resolve(A)
    container.resolve(B)

    await LifecycleManager(container).shutdown()
    assert log == ["B", "A"]


@pytest.mark.asyncio
async def test_shutdown_continues_after_individual_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fired: list[str] = []

    class Bad:
        async def on_app_shutdown(self) -> None:
            fired.append("bad")
            raise RuntimeError("close-failed")

    class Good:
        async def on_app_shutdown(self) -> None:
            fired.append("good")

    container = Container()
    container.register(Bad)
    container.register(Good)
    container.resolve(Bad)
    container.resolve(Good)

    caplog.set_level(logging.ERROR, logger="ajolopy.lifecycle")
    manager = LifecycleManager(container)
    await manager.shutdown()

    # Reverse order: Good first, then Bad.
    assert fired == ["good", "bad"]
    # Bad's exception logged but didn't stop the loop.
    assert any(
        record.name == "ajolopy.lifecycle" and "close-failed" in record.message
        for record in caplog.records
    )
    assert len(manager.shutdown_errors) == 1
    qualname, exc = manager.shutdown_errors[0]
    assert qualname == "test_shutdown_continues_after_individual_failure.<locals>.Bad"
    assert isinstance(exc, RuntimeError)


@pytest.mark.asyncio
async def test_shutdown_without_bootstrap_is_noop_when_no_singletons_cached() -> None:
    container = Container()
    # No singletons resolved → iter_singletons yields nothing.
    manager = LifecycleManager(container)
    await manager.shutdown()
    assert manager.shutdown_errors == []


@pytest.mark.asyncio
async def test_singleton_without_shutdown_hook_is_skipped() -> None:
    class WithoutHook:
        pass

    log: list[str] = []

    class WithHook:
        async def on_app_shutdown(self) -> None:
            log.append("hook")

    container = Container()
    container.register(WithoutHook)
    container.register(WithHook)
    container.resolve(WithoutHook)
    container.resolve(WithHook)

    await LifecycleManager(container).shutdown()
    assert log == ["hook"]
