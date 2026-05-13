"""``LifecycleManager`` — fires hooks on the container's cached singletons.

The manager is a thin orchestrator over :meth:`Container.iter_singletons`
(from AJ-11). Two well-defined phases at bootstrap, one at shutdown:

- **bootstrap phase 1** — calls ``on_module_init`` on each singleton in
  first-resolution order.
- **bootstrap phase 2** — calls ``on_app_bootstrap`` on each, same order.
  Splitting the phases lets every service finish its own setup before
  any cross-service "everything is wired" hook fires.
- **shutdown** — calls ``on_app_shutdown`` on each singleton in *reverse*
  first-resolution order, so dependencies stay alive while their
  dependents close.

Init / bootstrap errors are fatal — the manager re-raises them so the
caller (``AjolopyFactory.create`` in AJ-14) can terminate the process.
Shutdown errors are logged and collected in
:attr:`LifecycleManager.shutdown_errors` so the caller decides whether
to exit non-zero.
"""

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ajolopy.di import Container

_LOGGER = logging.getLogger("ajolopy.lifecycle")

_INIT_HOOK = "on_module_init"
_BOOTSTRAP_HOOK = "on_app_bootstrap"
_SHUTDOWN_HOOK = "on_app_shutdown"


class LifecycleManager:
    """Fires lifecycle hooks against the cached singletons of a container.

    Hold no state of its own beyond a reference to the container and
    the ``shutdown_errors`` list. Multiple managers over the same
    container would re-fire all hooks; production callers
    (``AjolopyFactory``) build exactly one per app.
    """

    def __init__(self, container: Container) -> None:
        self._container = container
        self.shutdown_errors: list[tuple[str, BaseException]] = []
        """``(qualname, exception)`` per failed ``on_app_shutdown`` hook.

        Populated only after :meth:`shutdown` runs. Callers inspect
        the list to decide their exit code.
        """

    async def bootstrap(self) -> None:
        """Run ``on_module_init`` then ``on_app_bootstrap`` on every singleton.

        First-failure-aborts semantics: a hook that raises stops the
        rest of the phase and propagates to the caller. Singletons
        already initialised in the failing phase keep whatever state
        they built — the caller decides whether to attempt shutdown.
        """
        instances = list(self._container.iter_singletons())
        for instance in instances:
            await _fire_hook(instance, _INIT_HOOK)
        for instance in instances:
            await _fire_hook(instance, _BOOTSTRAP_HOOK)

    async def shutdown(self) -> None:
        """Run ``on_app_shutdown`` on every singleton in reverse order.

        Errors are caught, logged at ``ERROR`` via the
        ``ajolopy.lifecycle`` logger, and appended to
        :attr:`shutdown_errors`. The loop always finishes so a single
        bad pool does not block the rest from closing.
        """
        self.shutdown_errors = []
        instances = list(self._container.iter_singletons())
        for instance in reversed(instances):
            try:
                await _fire_hook(instance, _SHUTDOWN_HOOK)
            except Exception as exc:
                # Best-effort shutdown: a single bad pool must not block
                # the rest from closing. ``KeyboardInterrupt`` / ``SystemExit``
                # are deliberately left unhandled so the user can abort the
                # shutdown loop with Ctrl-C if it stalls.
                qualname = type(instance).__qualname__
                _LOGGER.error("Shutdown hook on %s raised: %s", qualname, exc, exc_info=True)
                self.shutdown_errors.append((qualname, exc))


async def _fire_hook(instance: object, hook_name: str) -> None:
    """Invoke ``instance.hook_name()`` if it exists.

    Async hooks are awaited directly; sync hooks are dispatched via
    :func:`asyncio.to_thread` so they cannot block the event loop
    — matching ``@Tool``'s precedent (AJ-2).
    """
    hook = getattr(instance, hook_name, None)
    if hook is None or not callable(hook):
        return
    if inspect.iscoroutinefunction(hook):
        await hook()
        return
    # Sync hooks dispatched via ``asyncio.to_thread`` so they cannot
    # block the event loop. A sync hook that *returns* a coroutine is
    # a programming error (Python emits ``RuntimeWarning: coroutine was
    # never awaited``); the framework does not paper over it.
    await asyncio.to_thread(hook)
