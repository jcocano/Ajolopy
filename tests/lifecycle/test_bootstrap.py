"""Bootstrap phase 1 (on_module_init) + phase 2 (on_app_bootstrap)."""

from unittest.mock import AsyncMock

import pytest

from ajolopy.di import Container
from ajolopy.lifecycle import LifecycleManager


@pytest.mark.asyncio
async def test_bootstrap_phases_run_in_resolution_order() -> None:
    log: list[str] = []

    class A:
        async def on_module_init(self) -> None:
            log.append("A.init")

        async def on_app_bootstrap(self) -> None:
            log.append("A.bootstrap")

    class B:
        async def on_module_init(self) -> None:
            log.append("B.init")

        async def on_app_bootstrap(self) -> None:
            log.append("B.bootstrap")

    container = Container()
    container.register(A)
    container.register(B)
    container.resolve(A)
    container.resolve(B)

    await LifecycleManager(container).bootstrap()
    assert log == ["A.init", "B.init", "A.bootstrap", "B.bootstrap"]


@pytest.mark.asyncio
async def test_singleton_missing_init_is_skipped_in_phase_one() -> None:
    log: list[str] = []

    class BootstrapOnly:
        async def on_app_bootstrap(self) -> None:
            log.append("only-bootstrap")

    container = Container()
    container.register(BootstrapOnly)
    container.resolve(BootstrapOnly)

    await LifecycleManager(container).bootstrap()
    assert log == ["only-bootstrap"]


@pytest.mark.asyncio
async def test_singleton_without_any_hooks_is_a_noop() -> None:
    class NoHooks:
        pass

    container = Container()
    container.register(NoHooks)
    container.resolve(NoHooks)
    # Must not raise.
    await LifecycleManager(container).bootstrap()


@pytest.mark.asyncio
async def test_async_hook_is_awaited() -> None:
    spy = AsyncMock()

    class Holder:
        async def on_module_init(self) -> None:
            await spy()

    container = Container()
    container.register(Holder)
    container.resolve(Holder)

    await LifecycleManager(container).bootstrap()
    spy.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_hook_dispatched_via_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    original = asyncio.to_thread
    calls: list[object] = []

    async def spy(fn, *a, **kw):
        calls.append(fn)
        return await original(fn, *a, **kw)

    monkeypatch.setattr(asyncio, "to_thread", spy)

    class Holder:
        def on_module_init(self) -> None:
            pass

    container = Container()
    container.register(Holder)
    instance = container.resolve(Holder)

    await LifecycleManager(container).bootstrap()
    assert calls == [instance.on_module_init]


@pytest.mark.asyncio
async def test_hook_return_value_is_discarded() -> None:
    class Holder:
        async def on_module_init(self) -> str:
            return "ignored"

    container = Container()
    container.register(Holder)
    container.resolve(Holder)
    # Must not raise; return value is ignored.
    await LifecycleManager(container).bootstrap()


@pytest.mark.asyncio
async def test_on_module_init_failure_aborts_phase_one() -> None:
    fired: list[str] = []

    class Bad:
        async def on_module_init(self) -> None:
            fired.append("bad")
            raise RuntimeError("boom")

    class After:
        async def on_module_init(self) -> None:
            fired.append("after")

    container = Container()
    container.register(Bad)
    container.register(After)
    container.resolve(Bad)
    container.resolve(After)

    with pytest.raises(RuntimeError, match="boom"):
        await LifecycleManager(container).bootstrap()

    assert fired == ["bad"]  # second singleton not touched


@pytest.mark.asyncio
async def test_on_app_bootstrap_failure_aborts_after_phase_one_completes() -> None:
    fired: list[str] = []

    class A:
        async def on_module_init(self) -> None:
            fired.append("A.init")

        async def on_app_bootstrap(self) -> None:
            fired.append("A.bootstrap")
            raise RuntimeError("boom-bootstrap")

    class B:
        async def on_module_init(self) -> None:
            fired.append("B.init")

        async def on_app_bootstrap(self) -> None:
            fired.append("B.bootstrap")

    container = Container()
    container.register(A)
    container.register(B)
    container.resolve(A)
    container.resolve(B)

    with pytest.raises(RuntimeError, match="boom-bootstrap"):
        await LifecycleManager(container).bootstrap()

    # Phase 1 ran for both; phase 2 stopped at A.
    assert fired == ["A.init", "B.init", "A.bootstrap"]
