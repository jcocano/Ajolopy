"""HTTP application factory and route registration.

Exposes the low-level functional API (``create_app`` + ``add_route``) that
the higher-level ``@Controller`` / ``@Get`` decorators (AJ-10 / AJ-16) will
compile down to. Handlers in this commit accept ``request: Request`` only;
the param-injection pipeline (Body / Query / Param / Header) lands with
the introspection module added by a subsequent commit.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .errors import HttpHandlerConfigError

if TYPE_CHECKING:
    from starlette.requests import Request

_ALLOWED_METHODS: frozenset[str] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)

type Handler = Callable[..., Any]
"""A user handler. May be ``async def`` or sync ``def``.

Sync handlers are dispatched via :func:`asyncio.to_thread` so they cannot
block the event loop. The signature is currently restricted to a single
``request: Request`` parameter; the introspection-driven multi-parameter
form lands with the params commit.
"""


def create_app(*, routes: list[Route] | None = None) -> Starlette:
    """Create a Starlette app wired with the framework's defaults.

    Pass ``routes=[Route(...)]`` to register additional routes directly
    against Starlette's native API (escape hatch). Use
    :func:`add_route` for routes that should go through the framework's
    pipe + filter pipeline.
    """
    extra_routes: list[Route] = list(routes) if routes is not None else []
    return Starlette(routes=extra_routes)


def add_route(
    app: Starlette,
    method: str,
    path: str,
    handler: Handler,
) -> None:
    """Register ``handler`` at ``(method, path)`` on ``app``.

    The handler may be a coroutine function or a sync callable. Sync
    callables are dispatched via :func:`asyncio.to_thread` so they cannot
    block the event loop.
    """
    upper = method.upper()
    if upper not in _ALLOWED_METHODS:
        name = getattr(handler, "__qualname__", repr(handler))
        raise HttpHandlerConfigError(
            f"Unsupported HTTP method {method!r} for handler {name}. "
            f"Allowed: {sorted(_ALLOWED_METHODS)}"
        )
    endpoint = _build_endpoint(handler)
    app.router.routes.append(Route(path, endpoint, methods=[upper]))


def _build_endpoint(handler: Handler) -> Callable[[Request], Awaitable[Response]]:
    is_async = inspect.iscoroutinefunction(handler)

    async def endpoint(request: Request) -> Response:
        if is_async:
            result = await handler(request)
        else:
            result = await asyncio.to_thread(handler, request)
        return _serialise_response(result)

    return endpoint


def _serialise_response(value: object) -> Response:
    """Convert a handler's return value into a Starlette ``Response``.

    Supported return types:

    - ``None`` → ``204 No Content``.
    - ``Response`` (any subclass, including ``StreamingResponse``) →
      forwarded verbatim.
    - ``BaseModel`` → ``JSONResponse`` with ``model.model_dump(mode="json")``.
    - ``dict`` → ``JSONResponse`` with the dict as body.

    Anything else raises ``TypeError`` at request time; the default
    ``Exception`` filter (lands later) turns this into a ``500`` with the
    framework's no-leak envelope.
    """
    if value is None:
        return Response(status_code=204)
    if isinstance(value, Response):
        return value
    if isinstance(value, BaseModel):
        return JSONResponse(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return JSONResponse(value)
    raise TypeError(
        f"Handler returned {type(value).__name__}; expected dict, BaseModel, "
        f"Response (or subclass), or None."
    )
