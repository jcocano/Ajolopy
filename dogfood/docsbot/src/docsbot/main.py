"""ASGI entry point — works with both ``ajolopy dev`` and bare uvicorn.

Two public attributes:

- ``ajolopy_app`` — the framework's :class:`AjolopyApp` wrapper. Holds
  the compiled module, the populated DI container, the Starlette HTTP
  app, and the lifecycle manager. Tests and ``ajolopy dev`` use this
  (they understand the wrapper).

- ``app`` — the underlying Starlette ASGI3 callable, suitable for bare
  uvicorn (``uvicorn docsbot.main:app``). The wrapper itself does not
  implement the ASGI3 protocol; uvicorn needs the Starlette instance.

Why this split:
    Bare uvicorn does not await async factories and does not understand
    :class:`AjolopyApp` as an ASGI callable directly. Without exposing
    the inner Starlette app, every probe (including ``/health``)
    returned 500 in the deployed container. ``ajolopy dev`` happens to
    handle the wrapper internally and so disguised the gap locally.

Caveat — lifecycle hooks: mounting ``app`` (Starlette) instead of
:meth:`AjolopyApp.listen` skips the framework's
``on_app_bootstrap`` / ``on_app_shutdown`` hooks. The docsbot does
not currently declare any, so this is benign here; revisit if/when
this app grows lifecycle work.
"""

import asyncio

from ajolopy import AjolopyApp, AjolopyFactory
from docsbot.app_module import AppModule


async def build_app() -> AjolopyApp:
    """Async factory. Tests + ``ajolopy dev`` use this path."""
    return await AjolopyFactory.create(AppModule)


# Pre-build once at module import. Production uvicorn mounts
# ``docsbot.main:app`` (the Starlette inner app) directly.
ajolopy_app: AjolopyApp = asyncio.run(build_app())
app = ajolopy_app.http


def main() -> None:
    """Synchronous wrapper for ``python -m docsbot.main``."""
    # ``ajolopy_app`` / ``app`` are constructed at import time; nothing
    # more to do here for the smoke path. Production servers (uvicorn,
    # hypercorn, etc.) mount ``docsbot.main:app`` directly without
    # invoking ``main()``.


if __name__ == "__main__":
    main()
