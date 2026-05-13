"""Register ``@Stream``-marked methods as Starlette SSE routes.

``mount_streams(app, items)`` is the explicit two-line wiring path. The
one-liner ``create_app(streams=[...])`` (AJ-15's ``create_app`` extended
by this item) forwards to ``mount_streams`` after the app is built.

Each item is either a class (instantiated via ``Cls()``) or a pre-built
instance. Required constructor arguments raise :class:`StreamConfigError`
with guidance pointing to AJ-14 (full DI), which will lift the
zero-arg restriction.
"""

import inspect
from typing import TYPE_CHECKING

from starlette.routing import Route

from ajolopy.http.introspect import introspect_handler
from ajolopy.http.pipes import Pipe, ValidationPipe

from .decorator import iter_stream_methods
from .errors import StreamConfigError
from .runtime import make_sse_handler

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.applications import Starlette

_PIPE_STATE_ATTR = "ajolopy_pipe"


def mount_streams(app: Starlette, items: Iterable[type | object]) -> None:
    """Walk every ``@Stream``-marked method on ``items`` and register routes.

    Duplicate ``(method, path)`` pairs across all items raise
    :class:`StreamConfigError` so collisions surface at boot rather than
    silently shadowing routes.
    """
    pipe = _resolve_pipe(app)
    items_list = list(items)
    instances = [_normalise(item) for item in items_list]

    seen: dict[tuple[str, str], str] = {}
    for instance in instances:
        cls_name = type(instance).__qualname__
        marked = list(iter_stream_methods(instance))
        if not marked:
            raise StreamConfigError(
                f"Class {cls_name!r} passed to mount_streams has no "
                f"@Stream-marked methods. Decorate at least one method or "
                f"drop the class from the list."
            )
        for _attr_name, bound_method, metadata in marked:
            key = (metadata.method, metadata.path)
            existing = seen.get(key)
            new_qualname = metadata.handler.__qualname__
            if existing is not None:
                raise StreamConfigError(
                    f"Duplicate @Stream route {metadata.method} "
                    f"{metadata.path!r}: both {existing} and {new_qualname} "
                    f"declare it."
                )
            seen[key] = new_qualname

            resolved_params = introspect_handler(bound_method, metadata.path)
            endpoint = make_sse_handler(
                bound_method=bound_method,
                metadata=metadata,
                resolved_params=resolved_params,
                pipe=pipe,
            )
            app.router.routes.append(Route(metadata.path, endpoint, methods=[metadata.method]))


def _resolve_pipe(app: Starlette) -> Pipe:
    """Return the ``Pipe`` stored on ``app.state`` by AJ-15's ``create_app``.

    Mirrors :func:`ajolopy.http.app._get_pipe` so a streams-only app
    built directly via Starlette (no ``create_app``) still resolves a
    default ``ValidationPipe`` instead of crashing.
    """
    pipe = getattr(app.state, _PIPE_STATE_ATTR, None)
    if not isinstance(pipe, Pipe):
        pipe = ValidationPipe()
        app.state.ajolopy_pipe = pipe
    return pipe


def _normalise(item: type | object) -> object:
    """Coerce a class to a zero-arg instance; pass instances through.

    The zero-arg restriction lifts when AJ-14 (``AjolopyFactory``)
    lands — DI resolution will fill required constructor parameters.
    """
    if not isinstance(item, type):
        return item

    try:
        sig = inspect.signature(item)
    except (TypeError, ValueError) as exc:
        raise StreamConfigError(
            f"mount_streams could not introspect {item.__qualname__}: {exc}. "
            f"Pass a pre-built instance: mount_streams(app, [{item.__name__}(...)])."
        ) from exc

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        is_required = param.default is inspect.Parameter.empty and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
        if is_required:
            raise StreamConfigError(
                f"Class {item.__qualname__} requires constructor argument "
                f"{name!r}. Pass a pre-built instance — "
                f"mount_streams(app, [{item.__name__}(...)]) — or wait "
                f"for AJ-14 (AjolopyFactory) to handle full DI."
            )

    try:
        return item()
    except Exception as exc:
        raise StreamConfigError(
            f"Failed to instantiate {item.__qualname__}() in mount_streams: "
            f"{exc}. Pass a pre-built instance or wait for AJ-14."
        ) from exc
