"""ASGI entry point — invoked by ``ajolopy dev``.

The CLI's auto-detection algorithm (AJ-32) resolves
``src/<package>/main.py:app`` to this module's ``app`` attribute. ``app``
is intentionally a zero-arg coroutine: uvicorn awaits it at server boot
and the framework's factory builds the :class:`AjolopyApp` lazily, so
``python -m memory_assistant.main`` can share the same target without
forking.
"""

import asyncio

from ajolopy import AjolopyFactory
from memory_assistant.app_module import AppModule


async def app() -> object:
    """Build the :class:`AjolopyApp` instance lazily.

    ``ajolopy dev`` awaits this coroutine on server boot; tests can await
    it inside :func:`asyncio.run`.
    """
    return await AjolopyFactory.create(AppModule)


def main() -> None:
    """Synchronous wrapper for ``python -m memory_assistant.main``."""
    asyncio.run(app())


if __name__ == "__main__":
    main()
