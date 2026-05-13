"""HTTP application factory and route registration.

Exposes the low-level functional API (``create_app`` + ``add_route``) that
the higher-level ``@Controller`` / ``@Get`` decorators (AJ-10 / AJ-16) will
compile down to. Handlers in this commit accept ``request: Request`` only;
the param-injection pipeline (Body / Query / Param / Header) lands with
the introspection module added by a subsequent commit.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .errors import HttpHandlerConfigError
from .filters import DEFAULT_FILTERS, ExceptionFilter, get_catches

if TYPE_CHECKING:
    from starlette.requests import Request

type FilterSpec = ExceptionFilter[Any] | type[ExceptionFilter[Any]]

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


def create_app(
    *,
    routes: list[Route] | None = None,
    exception_filters: Sequence[FilterSpec] | None = None,
) -> Starlette:
    """Create a Starlette app wired with the framework's defaults.

    The default exception filters (``HttpException`` → JSON envelope,
    ``pydantic.ValidationError`` → 422, catch-all ``Exception`` → logged
    500) are always registered first. Pass user filters via
    ``exception_filters=[...]`` (classes are instantiated with no args;
    pre-built instances are accepted as well). User filters that
    ``@Catch`` the same class as a default override the default.

    Pass ``routes=[Route(...)]`` to register additional routes directly
    against Starlette's native API (escape hatch). Use
    :func:`add_route` for routes that should go through the framework's
    pipe + filter pipeline.
    """
    extra_routes: list[Route] = list(routes) if routes is not None else []
    user_specs: Sequence[FilterSpec] = exception_filters if exception_filters is not None else ()
    handlers = _build_exception_handlers(user_specs)
    return Starlette(routes=extra_routes, exception_handlers=handlers)


def _build_exception_handlers(
    user_filters: Sequence[FilterSpec],
) -> dict[Any, Callable[..., Awaitable[Response]]]:
    """Compose the Starlette ``exception_handlers`` mapping.

    Defaults are added first; user filters follow. Each ``@Catch`` entry
    is inserted under every exception class it targets, with later
    insertions overwriting earlier ones for the same class.
    """
    handlers: dict[Any, Callable[..., Awaitable[Response]]] = {}
    for spec in (*DEFAULT_FILTERS, *user_filters):
        instance = spec() if isinstance(spec, type) else spec
        adapter = _adapt_filter(instance)
        for exc_cls in get_catches(type(instance)):
            handlers[exc_cls] = adapter
    return handlers


def _adapt_filter(
    instance: ExceptionFilter[Any],
) -> Callable[[Any, Exception], Awaitable[Response]]:
    """Wrap a filter instance into Starlette's ``(request, exc)`` callable shape."""

    async def handler(request: Any, exc: Exception) -> Response:
        return await instance.catch(exc, request)

    return handler


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
