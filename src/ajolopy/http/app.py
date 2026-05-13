"""HTTP application factory and route registration.

Exposes the low-level functional API (``create_app`` + ``add_route``) that
the higher-level ``@Controller`` / ``@Get`` decorators (AJ-10 / AJ-16) will
compile down to. Handlers in this commit accept ``request: Request`` only;
the param-injection pipeline (Body / Query / Param / Header) lands with
the introspection module added by a subsequent commit.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .errors import HttpHandlerConfigError
from .filters import DEFAULT_FILTERS, ExceptionFilter, get_catches
from .introspect import ResolvedParam, extract_raw, introspect_handler
from .pipes import Pipe, ValidationPipe

if TYPE_CHECKING:
    from starlette.requests import Request

type FilterSpec = ExceptionFilter[Any] | type[ExceptionFilter[Any]]
_PIPE_STATE_ATTR = "ajolopy_pipe"

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
    pipe: Pipe | None = None,
    streams: Iterable[type | object] | None = None,
) -> Starlette:
    """Create a Starlette app wired with the framework's defaults.

    The default exception filters (``HttpException`` → JSON envelope,
    ``pydantic.ValidationError`` → 422, catch-all ``Exception`` → logged
    500) are always registered first. Pass user filters via
    ``exception_filters=[...]`` (classes are instantiated with no args;
    pre-built instances are accepted as well). User filters that
    ``@Catch`` the same class as a default override the default.

    ``pipe=`` swaps in a custom :class:`~ajolopy.http.pipes.Pipe` for the
    default :class:`~ajolopy.http.pipes.ValidationPipe`; the same pipe is
    applied to every handler registered via :func:`add_route`.

    Pass ``routes=[Route(...)]`` to register additional routes directly
    against Starlette's native API (escape hatch). Use
    :func:`add_route` for routes that should go through the framework's
    pipe + filter pipeline.

    ``streams=[Cls, instance, ...]`` forwards to
    :func:`ajolopy.stream.mount_streams` so every ``@Stream``-marked
    method on the provided classes / instances becomes an SSE route on
    the app. The kwarg is opt-in; ``None`` leaves the app unchanged.
    """
    extra_routes: list[Route] = list(routes) if routes is not None else []
    user_specs: Sequence[FilterSpec] = exception_filters if exception_filters is not None else ()
    handlers = _build_exception_handlers(user_specs)
    app = Starlette(routes=extra_routes, exception_handlers=handlers)
    setattr(app.state, _PIPE_STATE_ATTR, pipe if pipe is not None else ValidationPipe())
    if streams is not None:
        # Lazy import: ajolopy.stream depends on ajolopy.http, so the
        # reverse direction must stay deferred to avoid a cycle.
        from ajolopy.stream import mount_streams

        mount_streams(app, streams)
    return app


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
    block the event loop. Parameter injection (Body / Query / Param /
    Header) is resolved from the handler's signature at registration
    time.
    """
    upper = method.upper()
    if upper not in _ALLOWED_METHODS:
        name = getattr(handler, "__qualname__", repr(handler))
        raise HttpHandlerConfigError(
            f"Unsupported HTTP method {method!r} for handler {name}. "
            f"Allowed: {sorted(_ALLOWED_METHODS)}"
        )
    resolved_params = introspect_handler(handler, path)
    pipe = _get_pipe(app)
    endpoint = _build_endpoint(handler, resolved_params, pipe)
    app.router.routes.append(Route(path, endpoint, methods=[upper]))


def _get_pipe(app: Starlette) -> Pipe:
    pipe = getattr(app.state, _PIPE_STATE_ATTR, None)
    if not isinstance(pipe, Pipe):
        # Apps not built via ``create_app`` (e.g. tests) get the default.
        pipe = ValidationPipe()
        setattr(app.state, _PIPE_STATE_ATTR, pipe)
    return pipe


def _build_endpoint(
    handler: Handler,
    resolved_params: list[ResolvedParam],
    pipe: Pipe,
) -> Callable[[Request], Awaitable[Response]]:
    is_async = inspect.iscoroutinefunction(handler)

    async def endpoint(request: Request) -> Response:
        kwargs: dict[str, Any] = {}
        for rp in resolved_params:
            raw = await extract_raw(request, rp)
            kwargs[rp.name] = await pipe.transform(raw, param=rp)
        if is_async:
            result = await handler(**kwargs)
        else:
            result = await asyncio.to_thread(handler, **kwargs)
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
