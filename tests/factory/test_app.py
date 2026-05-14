"""Acceptance: ``AjolopyApp`` lifecycle, pass-throughs, context manager."""

import asyncio

import pytest
from starlette.applications import Starlette

from ajolopy import AjolopyFactory, Injectable, Module
from ajolopy.http.pipes import ValidationPipe


@pytest.mark.asyncio
async def test_aclose_fires_on_app_shutdown_in_reverse_order() -> None:
    seen: list[str] = []

    @Injectable
    class First:
        async def on_app_shutdown(self) -> None:
            seen.append("first")

    @Injectable
    class Second:
        def __init__(self, first: First) -> None:
            self.first = first

        async def on_app_shutdown(self) -> None:
            seen.append("second")

    @Module(providers=[First, Second])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    # Resolve Second so it appears in iter_singletons after First.
    app.container.resolve(Second)
    await app.aclose()

    # Reverse first-resolution order: Second (resolved second) shuts down first.
    assert seen == ["second", "first"]


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    seen: list[str] = []

    @Injectable
    class Svc:
        async def on_app_shutdown(self) -> None:
            seen.append("shutdown")

    @Module(providers=[Svc])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    app.container.resolve(Svc)

    await app.aclose()
    await app.aclose()  # second call is no-op

    assert seen == ["shutdown"]


@pytest.mark.asyncio
async def test_async_context_manager_form() -> None:
    seen: list[str] = []

    @Injectable
    class Svc:
        async def on_app_shutdown(self) -> None:
            seen.append("ctx_exit")

    @Module(providers=[Svc])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    app.container.resolve(Svc)

    async with app as inside:
        assert inside is app
    # aclose ran on context exit.
    assert seen == ["ctx_exit"]


@pytest.mark.asyncio
async def test_use_global_pipes_replaces_pipe() -> None:
    from ajolopy.http.app import _get_pipe

    @Module()
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        custom_pipe = ValidationPipe()
        app.use_global_pipes(custom_pipe)
        assert _get_pipe(app.http) is custom_pipe
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_use_global_pipes_zero_pipes_is_noop() -> None:
    @Module()
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        app.use_global_pipes()  # zero pipes — no-op, no error
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_use_global_pipes_more_than_one_raises() -> None:
    @Module()
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        with pytest.raises(TypeError, match="at most one pipe"):
            app.use_global_pipes(ValidationPipe(), ValidationPipe())
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_use_global_filters_registers_on_starlette() -> None:
    from typing import override

    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    from ajolopy.http.filters import Catch, ExceptionFilter

    class _MyError(Exception):
        pass

    @Catch(_MyError)
    class MyFilter(ExceptionFilter[_MyError]):
        @override
        async def catch(self, exc: _MyError, request: Request) -> Response:
            return JSONResponse({"caught": True})

    @Module()
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        app.use_global_filters(MyFilter())
        assert _MyError in app.http.exception_handlers
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_listen_ephemeral_port_serves_then_cancels() -> None:
    @Module()
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    listen_task = asyncio.create_task(app.listen(port=0, host="127.0.0.1"))

    # Give the server a tick to start.
    await asyncio.sleep(0.05)
    listen_task.cancel()

    # Cancellation is the success path. CodeQL flags ``await`` inside
    # ``contextlib.suppress`` as "no effect" (false positive), so we keep
    # the explicit try/except shape and suppress SIM105 locally.
    async with asyncio.timeout(2.0):
        try:  # noqa: SIM105 — see comment above
            await listen_task
        except asyncio.CancelledError:
            # We explicitly cancelled ``listen_task`` above; this is the
            # expected path. Swallow it so the test continues to the
            # ``aclose`` assertion below.
            pass
    # aclose ran via listen()'s finally; the inner _closed flag is set
    # so a second aclose is a no-op (no double-shutdown errors).
    await app.aclose()


def test_http_is_starlette_instance() -> None:
    """``AjolopyApp.http`` exposes the actual Starlette object."""

    @Module()
    class AppModule:
        pass

    app = asyncio.run(AjolopyFactory.create(AppModule))
    try:
        assert isinstance(app.http, Starlette)
    finally:
        asyncio.run(app.aclose())
