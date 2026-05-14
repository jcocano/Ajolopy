"""Register every ``@MCPServer``-marked target on a Starlette app.

``mount_mcp_servers(app, items)`` is the standalone API; the
``create_app(mcp_servers=[...])`` kwarg is sugar that calls it after
the app is built (mirrors the AJ-3 stream mount layer exactly).

The mount layer detects path collisions across every transport before
it touches the router, so a misconfigured second class never silently
shadows the first. ``@UseGuards``-stamped host classes have their
guard chain resolved here via :func:`resolve_guard_chain` and wired
into the route through :func:`apply_guard_chain` (AJ-17). stdio
targets are rejected at mount time -- they belong to the CLI.
"""

import inspect
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from starlette.routing import Route

from ajolopy.guards.decorator import GUARDS_META_ATTR
from ajolopy.guards.runtime import apply_guard_chain, resolve_guard_chain

from .decorator import MCP_SERVER_META_ATTR
from .errors import MCPServerConfigError
from .metadata import MCPServerMetadata
from .runtime import MCPServerRuntime
from .transports.http import build_streamable_http_endpoint
from .transports.sse import build_sse_get_endpoint

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response


def mount_mcp_servers(
    app: Starlette,
    items: Iterable[type[Any] | object],
) -> None:
    """Walk ``items`` and register their @MCPServer routes on ``app``.

    Each item is either a class (instantiated zero-arg, mirroring
    :func:`ajolopy.stream.mount_streams`) or a pre-built instance. The
    instance path is the recommended seam for classes with required
    constructor arguments (DI is a v0.2 concern -- AJ-14).

    Path collisions across the items, classes that are not
    ``@MCPServer``-decorated, and stdio targets passed to the HTTP
    mount path all raise :class:`MCPServerConfigError`.
    """
    items_list = list(items)
    runtimes: list[MCPServerRuntime] = []
    seen: dict[tuple[str, str], str] = {}

    for item in items_list:
        cls, instance = _resolve_target(item)
        metadata = _read_metadata(cls)
        if metadata.transport == "stdio":
            raise MCPServerConfigError(
                f'@MCPServer({cls.__qualname__}, transport="stdio") cannot '
                f"be mounted on the HTTP app -- stdio servers run under the "
                f"CLI: `ajolopy mcp-serve <module>:{cls.__name__}`."
            )
        runtime = MCPServerRuntime(metadata, instance=instance)
        # Resolve guards before booting so a misconfigured chain raises
        # before the server warms up.
        guards = resolve_guard_chain(cls, None)
        # ``mount`` emits the boot span; runtime.instance materialises the
        # host class to surface required-arg errors at mount time.
        runtime.emit_boot_span()
        _ = runtime.instance

        new_qualname = cls.__qualname__
        for method, path in _routes_for(metadata):
            key = (method, path)
            existing = seen.get(key)
            if existing is not None:
                raise MCPServerConfigError(
                    f"@MCPServer route collision on {method} {path!r}: "
                    f"both {existing} and {new_qualname} declare it."
                )
            seen[key] = new_qualname

        _register_routes(app, runtime, guards)
        runtimes.append(runtime)


def _resolve_target(item: type[Any] | object) -> tuple[type[Any], Any]:
    """Return ``(cls, instance_or_None)`` for an item.

    Instances are passed through verbatim (the runtime caches them);
    classes are NOT instantiated here -- the runtime does that lazily so
    the user sees the right exception path when the constructor blows up.
    """
    if isinstance(item, type):
        # Defensive check: classes with required-arg ``__init__`` are
        # caught by ``MCPServerRuntime.instance`` so the user gets the
        # documented "pass a pre-built instance" hint instead of a
        # cryptic TypeError. We still surface it eagerly at mount time.
        try:
            sig = inspect.signature(item)
        except (TypeError, ValueError) as exc:
            raise MCPServerConfigError(
                f"mount_mcp_servers could not introspect {item.__qualname__}: "
                f"{exc}. Pass a pre-built instance: "
                f"mount_mcp_servers(app, [{item.__name__}(...)])."
            ) from exc
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.default is inspect.Parameter.empty and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise MCPServerConfigError(
                    f"@MCPServer host class {item.__qualname__} requires "
                    f"constructor argument {name!r}. Pass a pre-built "
                    f"instance: mount_mcp_servers(app, "
                    f"[{item.__name__}(...)])."
                )
        return item, None
    return type(item), item


def _read_metadata(cls: type[Any]) -> MCPServerMetadata:
    metadata = cls.__dict__.get(MCP_SERVER_META_ATTR)
    if metadata is None:
        # Fall back to inherited metadata (subclassing a decorated class
        # is unusual but supported -- the subclass inherits the parent's
        # frozen wire tools).
        metadata = getattr(cls, MCP_SERVER_META_ATTR, None)
    if not isinstance(metadata, MCPServerMetadata):
        raise MCPServerConfigError(
            f"{cls.__qualname__} is not decorated with @MCPServer. "
            f"Apply @MCPServer(transport=...) before passing it to "
            f"mount_mcp_servers / create_app(mcp_servers=...)."
        )
    # If the user wrote @UseGuards INSIDE the @MCPServer decorator (so
    # the inner @UseGuards stamp would not have prevented the
    # decorator from running), and the transport is stdio, surface the
    # documented trust-boundary error at mount time too.
    if metadata.transport == "stdio" and cls.__dict__.get(GUARDS_META_ATTR) is not None:
        raise MCPServerConfigError(
            '@UseGuards is not supported on transport="stdio" -- the parent '
            'process is the trust boundary. Use transport="http" / "sse" '
            "if you need request-level auth."
        )
    return metadata


def _routes_for(metadata: MCPServerMetadata) -> list[tuple[str, str]]:
    """Return the ``(method, path)`` pairs registered by a single server."""
    if metadata.path is None:
        raise MCPServerConfigError("Internal error: stdio metadata reached the HTTP mount layer.")
    if metadata.transport == "http":
        return [("POST", metadata.path)]
    if metadata.transport == "sse":
        return [
            ("GET", metadata.path),
            ("POST", f"{metadata.path.rstrip('/')}/messages"),
        ]
    raise MCPServerConfigError(
        f"Unknown transport {metadata.transport!r} reached mount layer "
        f"(decoration-time validation should have caught it)."
    )


def _register_routes(
    app: Starlette,
    runtime: MCPServerRuntime,
    guards: tuple[Any, ...],
) -> None:
    """Attach the transport-specific endpoints to ``app.router``."""
    metadata = runtime.metadata
    if metadata.path is None:
        # Defensive: stdio targets are rejected upstream; reaching this
        # branch means the caller bypassed the public mount API.
        raise MCPServerConfigError("Internal error: stdio metadata reached the route register.")

    if metadata.transport == "http":
        mount = build_streamable_http_endpoint(runtime)
        endpoint: Callable[[Request], Awaitable[Response]] = mount.endpoint
        if guards:
            endpoint = apply_guard_chain(endpoint, guards)
        app.router.routes.append(Route(metadata.path, endpoint, methods=["POST"]))
        _chain_lifespan(app, mount.lifespan)
        return

    if metadata.transport == "sse":
        mount = build_sse_get_endpoint(runtime, metadata.path)
        get_endpoint: Callable[[Request], Awaitable[Response]] = mount.get_endpoint
        post_endpoint: Callable[[Request], Awaitable[Response]] = mount.post_endpoint
        if guards:
            get_endpoint = apply_guard_chain(get_endpoint, guards)
            post_endpoint = apply_guard_chain(post_endpoint, guards)
        app.router.routes.append(Route(metadata.path, get_endpoint, methods=["GET"]))
        app.router.routes.append(
            Route(
                f"{metadata.path.rstrip('/')}/messages",
                post_endpoint,
                methods=["POST"],
            )
        )
        return


def _chain_lifespan(
    app: Starlette,
    extra: Callable[[], Any],
) -> None:
    """Compose ``extra`` into the app's existing lifespan context.

    Starlette's :class:`Router` stores the lifespan context manager on
    ``router.lifespan_context``; we replace it with a wrapper that
    drives the original lifespan inside the extra context manager so
    both run for the duration of the ASGI process. ``extra`` is the
    bare async-context factory returned by the transport modules.
    """
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def composed(host: Starlette) -> AsyncGenerator[None]:
        async with extra(), previous(host):
            yield

    app.router.lifespan_context = composed


__all__ = [
    "mount_mcp_servers",
]
