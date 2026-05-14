"""``AjolopyApp`` — the artifact :class:`AjolopyFactory.create` returns.

Wraps the compiled module, the populated container, and the Starlette
HTTP app behind a single object. Exposes a small async lifecycle
(``listen`` / ``aclose`` / ``__aenter__`` / ``__aexit__``) and two
NestJS-style pass-throughs (``use_global_pipes`` / ``use_global_filters``)
that mutate the underlying Starlette state.

The class holds **no state of its own** — every field is a reference
to an object built by the factory. Two ``AjolopyApp`` instances over
the same container would share state; production code builds exactly
one per process.
"""

from typing import TYPE_CHECKING, Any

from ajolopy.http import set_global_pipe

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.applications import Starlette

    from ajolopy.di import Container
    from ajolopy.http.filters import ExceptionFilter
    from ajolopy.http.pipes import Pipe
    from ajolopy.lifecycle import LifecycleManager
    from ajolopy.modules import CompiledModule


class AjolopyApp:
    """Runtime artifact produced by :meth:`AjolopyFactory.create`.

    Holds the compiled module graph, the populated DI container, the
    Starlette app, and the lifecycle manager. Callers either ``await
    app.listen(port)`` to start the server or use the async context
    manager form to exercise the app without starting a listener
    (useful in tests).
    """

    def __init__(
        self,
        *,
        compiled_module: CompiledModule,
        http: Starlette,
        lifecycle: LifecycleManager,
    ) -> None:
        self._compiled_module = compiled_module
        self._http = http
        self._lifecycle = lifecycle
        self._closed = False

    @property
    def compiled_module(self) -> CompiledModule:
        """The :class:`CompiledModule` produced by ``compile_module``."""
        return self._compiled_module

    @property
    def container(self) -> Container:
        """The :class:`Container` populated by ``compile_module``."""
        return self._compiled_module.container

    @property
    def http(self) -> Starlette:
        """The underlying Starlette app — escape hatch for raw middleware."""
        return self._http

    def use_global_pipes(self, *pipes: Pipe) -> None:
        """Replace the app's global :class:`Pipe`.

        Accepts a single pipe instance (NestJS-style ``app.use_global_pipes(ValidationPipe())``).
        Passing zero pipes is a no-op; passing more than one is a
        :class:`TypeError` — v0.1 supports exactly one global pipe.
        """
        if len(pipes) == 0:
            return
        if len(pipes) > 1:
            raise TypeError(
                f"use_global_pipes accepts at most one pipe (got {len(pipes)}); "
                f"v0.1 supports exactly one global pipe."
            )
        set_global_pipe(self._http, pipes[0])

    def use_global_filters(self, *filters: ExceptionFilter[Any]) -> None:
        """Register additional global :class:`ExceptionFilter` instances.

        Each filter's ``@Catch`` set is inserted into the underlying
        Starlette app's ``exception_handlers`` mapping. Filters that
        ``@Catch`` an exception class already handled by a default
        filter override the default for that class.
        """
        from ajolopy.http.filters import get_catches

        for filter_instance in filters:
            adapter = _adapt_filter_for_use_global(filter_instance)
            for exc_cls in get_catches(type(filter_instance)):
                self._http.exception_handlers[exc_cls] = adapter

    async def listen(self, port: int, *, host: str = "0.0.0.0") -> None:  # noqa: S104 — production HTTP servers bind to all interfaces by default; users override to "127.0.0.1" when needed
        """Start the uvicorn server and block until it stops.

        Cancellation propagates: if the caller cancels the task running
        ``listen``, the uvicorn server stops gracefully and ``aclose``
        runs in the ``finally`` block before the cancellation re-raises.
        ``port=0`` is supported for ephemeral-port tests.
        """
        from uvicorn import (
            Config,
            Server,
        )

        config = Config(
            app=self._http,
            host=host,
            port=port,
            log_config=None,  # the framework owns logging via structlog (AJ-29)
        )
        server = Server(config)
        try:
            await server.serve()
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Fire shutdown hooks + dispose internal references.

        Idempotent: a second call is a no-op. Walks
        :class:`LifecycleManager.shutdown` to fire ``on_app_shutdown``
        on every singleton in reverse order. Shutdown errors are
        collected on ``lifecycle.shutdown_errors`` (already populated
        by the manager) — callers inspect that list to decide their
        exit code.
        """
        if self._closed:
            return
        self._closed = True
        await self._lifecycle.shutdown()
        # MCP registry shutdown — closes every live MCP client (stdio
        # child processes, HTTP / SSE sessions). Best-effort: errors are
        # swallowed inside :meth:`MCPRegistry.shutdown` so a stuck client
        # cannot block the rest of teardown.
        from ajolopy.mcp import get_mcp_registry

        await get_mcp_registry().shutdown()

    async def __aenter__(self) -> AjolopyApp:
        """Async context manager entry — returns ``self``."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Async context manager exit — runs :meth:`aclose`."""
        await self.aclose()


def _adapt_filter_for_use_global(
    filter_instance: ExceptionFilter[Any],
) -> Callable[[Any, Exception], Awaitable[Any]]:
    """Wrap a filter instance into Starlette's ``(request, exc)`` callable shape.

    Mirrors :func:`ajolopy.http.app._adapt_filter`; lives here so the
    pass-through does not depend on private helpers of ``ajolopy.http``.
    """

    async def handler(request: Any, exc: Exception) -> Any:
        return await filter_instance.catch(exc, request)

    return handler
