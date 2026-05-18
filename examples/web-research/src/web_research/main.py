"""ASGI entry point — works with both ``ajolopy dev`` and bare uvicorn.

Two public attributes:

- ``ajolopy_app`` — the framework's :class:`AjolopyApp` wrapper. Holds
  the compiled module, the populated DI container, the Starlette HTTP
  app, and the lifecycle manager. Tests and ``ajolopy dev`` use this
  (they understand the wrapper).

- ``app`` — the underlying Starlette ASGI3 callable, suitable for bare
  uvicorn (``uvicorn web_research.main:app``). The wrapper itself
  does not implement the ASGI3 protocol; uvicorn needs the Starlette
  instance.

Why this split:
    Bare uvicorn's ``factory=True`` mode does not await async factories
    and does not understand :class:`AjolopyApp` as an ASGI callable
    directly. Without pre-building at import and exposing the inner
    Starlette app, every request returned 500
    (``TypeError: 'coroutine' object is not callable``). ``ajolopy dev``
    happens to handle the wrapper internally and so disguised the gap
    locally; the production path (bare uvicorn / Fly / Render) did not.

Caveat — lifecycle hooks: mounting ``app`` (Starlette) instead of
:meth:`AjolopyApp.listen` skips the framework's
``on_app_bootstrap`` / ``on_app_shutdown`` hooks. The web-research
example does not currently declare any; revisit if/when it grows
lifecycle work.
"""

import asyncio

from ajolopy import AjolopyApp, AjolopyFactory
from web_research.app_module import AppModule


async def build_app() -> AjolopyApp:
    """Async factory. Tests + ``ajolopy dev`` use this path."""
    return await AjolopyFactory.create(AppModule)


# Pre-build once at module import. Production uvicorn mounts
# ``web_research.main:app`` (the Starlette inner app) directly.
ajolopy_app: AjolopyApp = asyncio.run(build_app())
app = ajolopy_app.http


def main() -> None:
    """Synchronous wrapper for ``python -m web_research.main``."""
    # ``ajolopy_app`` / ``app`` are constructed at import time; nothing
    # more to do here for the smoke path. Production servers (uvicorn,
    # hypercorn, etc.) mount ``web_research.main:app`` directly without
    # invoking ``main()``.


if __name__ == "__main__":
    main()
