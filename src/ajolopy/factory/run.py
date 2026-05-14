"""``run()`` — the killer-demo convenience wrapper.

Twelve-line ``main.py`` snippet: ``run(AppModule, port=3000)`` is one
call that bootstraps the factory, installs SIGINT / SIGTERM handlers,
runs the server, and exits cleanly.

Users who need finer control (custom signal handling, programmatic
shutdown, multiple apps in one process) go through
:meth:`AjolopyFactory.create` + :meth:`AjolopyApp.listen` directly.
"""

import asyncio
import contextlib
import signal

from .factory import AjolopyFactory


def run(
    root_module: type,
    *,
    port: int = 3000,
    host: str = "0.0.0.0",  # noqa: S104 — convenience default for production servers; explicit "127.0.0.1" when local-only
) -> None:
    """Bootstrap and run the app, blocking until shutdown.

    Installs SIGINT / SIGTERM handlers that cancel the serve task so
    ``AjolopyApp.aclose`` fires via the ``listen`` ``finally`` block.

    Parameters
    ----------
    root_module:
        The application's root ``@Module``-decorated class.
    port:
        TCP port the server binds to. Default ``3000``.
    host:
        Interface the server binds to. Default ``"0.0.0.0"`` (all
        interfaces); use ``"127.0.0.1"`` to expose only locally.
    """
    asyncio.run(_run_async(root_module, port=port, host=host))


async def _run_async(root_module: type, *, port: int, host: str) -> None:
    app = await AjolopyFactory.create(root_module)
    loop = asyncio.get_running_loop()
    serve_task = asyncio.create_task(app.listen(port, host=host))

    def _request_stop() -> None:
        if not serve_task.done():
            serve_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        # ``add_signal_handler`` is unavailable on Windows event loops;
        # uvicorn ships its own SIGINT handler that will still work.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)

    # Expected cancellation: a signal handler cancels the serve task. The
    # ``listen`` ``finally`` block already ran ``aclose``; just let the
    # cancellation propagate out as a normal shutdown. SIM105 prefers
    # ``contextlib.suppress`` here but CodeQL flags the ``await`` inside
    # the context manager as "no effect" (false positive), so we keep
    # the explicit try/except shape and suppress SIM105 locally.
    try:  # noqa: SIM105 — see comment above
        await serve_task
    except asyncio.CancelledError:
        pass
