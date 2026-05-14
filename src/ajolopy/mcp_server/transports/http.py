"""Streamable-HTTP transport for ``@MCPServer``.

Wraps :class:`mcp.server.streamable_http_manager.StreamableHTTPSessionManager`
into a Starlette-compatible ASGI endpoint. The session manager owns a
long-lived task group that the SDK requires to run inside the host
app's lifespan; :func:`build_streamable_http_endpoint` returns both the
endpoint coroutine the mount layer registers AND an async-context
factory the mount layer chains into the Starlette ``lifespan_context``.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from starlette.responses import Response

from ajolopy.mcp_server.errors import MCPDependencyError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from starlette.requests import Request

    from ajolopy.mcp_server.runtime import MCPServerRuntime


@dataclass(slots=True)
class StreamableHTTPMount:
    """Bundle returned by :func:`build_streamable_http_endpoint`.

    ``endpoint`` is the Starlette-compatible request handler the mount
    layer hands to :class:`starlette.routing.Route`. ``lifespan`` is
    an async-context manager the mount layer chains into the app's
    ``lifespan_context`` so the session manager's task group lives for
    the lifetime of the ASGI process.
    """

    endpoint: Callable[[Request], Awaitable[Response]]
    lifespan: Callable[[], Any]


def build_streamable_http_endpoint(runtime: MCPServerRuntime) -> StreamableHTTPMount:
    """Return the ASGI endpoint + lifespan context for streamable HTTP.

    Builds the lowlevel ``mcp`` ``Server`` via the runtime and wraps it
    in a single :class:`StreamableHTTPSessionManager` instance. The
    session manager's ``run()`` is wrapped into the lifespan helper the
    caller chains into Starlette's lifespan -- per the SDK docs the
    manager can be started exactly once per instance.
    """
    try:
        from mcp.server.streamable_http_manager import (
            StreamableHTTPSessionManager,
        )
    except ImportError as exc:  # pragma: no cover - exercised in dependency test
        raise MCPDependencyError(
            "The 'mcp' SDK is required to mount @MCPServer over HTTP. "
            "Install it with 'pip install ajolopy[mcp]'."
        ) from exc

    server = runtime.build_server()
    session_manager = StreamableHTTPSessionManager(app=server, stateless=False)

    async def endpoint(request: Request) -> Response:
        # Hand the ASGI scope/receive/send back to the session manager.
        # Starlette wraps the underlying scope; the SDK reads from a
        # MutableMapping shape so it's safe to pass the Starlette scope.
        await session_manager.handle_request(
            request.scope,
            request.receive,
            request._send,  # pyright: ignore[reportPrivateUsage] -- Starlette's documented ASGI seam
        )
        # ``handle_request`` already wrote the full ASGI response. We
        # return a sentinel ``Response`` Starlette knows to ignore.
        return _AlreadySentResponse()

    @asynccontextmanager
    async def lifespan() -> AsyncGenerator[None]:
        async with session_manager.run():
            yield

    return StreamableHTTPMount(endpoint=endpoint, lifespan=lifespan)


class _AlreadySentResponse(Response):
    """Sentinel ``Response`` indicating the ASGI response was already sent.

    Starlette's ``Route`` endpoint contract calls the endpoint and
    awaits a ``Response``; Starlette then calls ``response(scope,
    receive, send)`` on the result. When the MCP session manager has
    already driven the ASGI cycle to completion we cannot let
    Starlette write again. Overriding ``__call__`` to be a no-op makes
    the dance safe.
    """

    def __init__(self) -> None:
        super().__init__(b"", status_code=200)

    @override
    async def __call__(
        self,
        scope: Any,
        receive: Any,
        send: Any,
    ) -> None:
        _ = (scope, receive, send)
        # Response already sent by the MCP session manager.
        return


__all__ = [
    "StreamableHTTPMount",
    "build_streamable_http_endpoint",
]
