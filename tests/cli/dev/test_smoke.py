"""Programmatic smoke test for ``ajolopy dev``.

Boots a :class:`uvicorn.Server` against a trivial ASGI app on an
ephemeral port, lets the server come up, sends ``SIGINT`` to the
current process to break out of the serve loop, and asserts on a
clean shutdown. Reload is OFF so we keep everything inside the test
process — uvicorn's reload pathway spawns a subprocess that would
make signal handling brittle.
"""

import asyncio
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable

import pytest

from ajolopy.cli.commands import dev as dev_cmd

# ---------------------------------------------------------------------------
# Minimal ASGI app — single GET / handler returning "ok".
# ---------------------------------------------------------------------------


async def _asgi_app(
    scope: dict[str, object],
    receive: Callable[[], Awaitable[dict[str, object]]],
    send: Callable[[dict[str, object]], Awaitable[None]],
) -> None:
    """Tiny ASGI app — answers any HTTP request with ``200 ok``."""
    if scope["type"] != "http":
        return
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})


def _free_port() -> int:
    """Return a kernel-assigned ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(predicate: Callable[[], bool], *, timeout_s: float = 5.0) -> bool:
    """Poll ``predicate`` every 50 ms until it returns ``True`` or times out."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class TestSmoke:
    def test_serves_one_request_and_shuts_down_cleanly(self) -> None:
        import uvicorn

        port = _free_port()
        config = uvicorn.Config(
            app=_asgi_app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            reload=False,
            access_log=False,
            ws="none",
        )
        server = uvicorn.Server(config)
        # uvicorn's signal handlers conflict with pytest's main-thread
        # signal expectations; disable them so we can stop the loop by
        # toggling ``server.should_exit``.
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

        exception: list[BaseException] = []

        def _serve() -> None:
            try:
                asyncio.run(server.serve())
            except BaseException as exc:  # pragma: no cover - defensive
                exception.append(exc)

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        try:
            assert _wait_for(lambda: getattr(server, "started", False)), (
                "uvicorn never finished startup within timeout"
            )

            url = f"http://127.0.0.1:{port}/"
            try:
                with urllib.request.urlopen(url, timeout=3.0) as response:  # noqa: S310
                    body = response.read()
                    assert response.status == 200
                    assert body == b"ok"
            except urllib.error.URLError as exc:  # pragma: no cover - debugging aid
                pytest.fail(f"could not reach dev server: {exc}")
        finally:
            server.should_exit = True
            thread.join(timeout=10)

        assert not thread.is_alive(), "uvicorn did not shut down after should_exit"
        assert not exception, f"serve() raised: {exception[0]!r}"

    def test_keyboard_interrupt_propagates_clean_exit(self) -> None:
        """SIGINT-style shutdown: trip should_exit + wait for graceful join.

        Mirrors what ``server.run()`` would do under a real Ctrl+C —
        uvicorn flips ``should_exit`` from its signal handler. We
        simulate that directly to keep the test from racing the OS
        signal queue while pytest owns the main thread.
        """
        import uvicorn

        port = _free_port()
        config = uvicorn.Config(
            app=_asgi_app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            reload=False,
            access_log=False,
            ws="none",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

        def _serve() -> None:
            asyncio.run(server.serve())

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()

        assert _wait_for(lambda: getattr(server, "started", False))

        # Schedule the shutdown trigger on a timer to mirror the SIGINT
        # arrival pattern: the user types Ctrl+C, uvicorn flips its
        # ``should_exit`` flag, and the loop returns.
        timer = threading.Timer(0.2, lambda: setattr(server, "should_exit", True))
        timer.start()
        try:
            thread.join(timeout=10)
        finally:
            timer.cancel()

        assert not thread.is_alive(), "uvicorn did not exit after should_exit"


class TestServerFactory:
    """Make sure :func:`_make_server` produces a real uvicorn.Server."""

    def test_make_server_returns_uvicorn_server(self) -> None:
        import uvicorn

        config = dev_cmd._build_config(
            module="some.module",
            var="app",
            host="127.0.0.1",
            port=0,
            reload=False,
            reload_dirs=[],
            include_env=False,
        )
        server = dev_cmd._make_server(config)
        assert isinstance(server, uvicorn.Server)
        assert server.config is config
