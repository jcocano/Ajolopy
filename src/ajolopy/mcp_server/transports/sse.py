"""SSE transport for ``@MCPServer``.

Wraps :class:`mcp.server.sse.SseServerTransport` into two
Starlette-compatible ASGI endpoints: the GET handler (sets up the SSE
read stream) and the POST handler at ``<path>/messages`` (delivers
client-to-server messages). Both endpoints are registered by the mount
layer; this module focuses on the per-endpoint adapter.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from starlette.responses import Response

from ajolopy.mcp_server.errors import MCPDependencyError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request

    from ajolopy.mcp_server.runtime import MCPServerRuntime

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SSEMount:
    """Bundle returned by the SSE transport builder.

    Both endpoints share the same :class:`SseServerTransport` instance
    so the POST handler routes messages to the GET handler's read
    stream. The mount layer registers both at the right paths and
    chains the guard chain through them.
    """

    get_endpoint: Callable[[Request], Awaitable[Response]]
    post_endpoint: Callable[[Request], Awaitable[Response]]


def build_sse_get_endpoint(runtime: MCPServerRuntime, path: str) -> SSEMount:
    """Return the SSE GET + POST endpoints wired to ``runtime``.

    The SDK's :class:`SseServerTransport` is instantiated with the POST
    endpoint path (``<path>/messages``) so it can write a ``message`` URL
    back to the client during the SSE handshake.
    """
    try:
        from mcp.server.sse import SseServerTransport
    except ImportError as exc:  # pragma: no cover - exercised in dependency test
        raise MCPDependencyError(
            "The 'mcp' SDK is required to mount @MCPServer over SSE. "
            "Install it with 'pip install ajolopy[mcp]'."
        ) from exc

    server = runtime.build_server()
    messages_path = f"{path.rstrip('/')}/messages"
    transport = SseServerTransport(messages_path)

    async def get_endpoint(request: Request) -> Response:
        async with transport.connect_sse(
            request.scope,
            request.receive,
            request._send,  # pyright: ignore[reportPrivateUsage] -- Starlette's documented ASGI seam
        ) as streams:
            read_stream, write_stream = streams
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        return _AlreadySentResponse()

    async def post_endpoint(request: Request) -> Response:
        await transport.handle_post_message(
            request.scope,
            request.receive,
            request._send,  # pyright: ignore[reportPrivateUsage] -- Starlette's documented ASGI seam
        )
        return _AlreadySentResponse()

    return SSEMount(get_endpoint=get_endpoint, post_endpoint=post_endpoint)


def build_sse_post_endpoint(mount: SSEMount) -> Callable[[Request], Awaitable[Response]]:
    """Return the SSE POST endpoint from a previously built :class:`SSEMount`.

    Symmetric helper kept for readability in the mount layer; the actual
    POST endpoint is constructed inside :func:`build_sse_get_endpoint`
    so both handlers share the same transport instance.
    """
    return mount.post_endpoint


class _AlreadySentResponse(Response):
    """Sentinel ``Response`` indicating the ASGI response was already sent."""

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
        return


__all__ = [
    "SSEMount",
    "build_sse_get_endpoint",
    "build_sse_post_endpoint",
]
