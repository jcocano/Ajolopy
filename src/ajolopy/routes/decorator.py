"""``@Get`` / ``@Post`` / ``@Put`` / ``@Patch`` / ``@Delete`` method decorators.

Each decorator validates its ``path`` argument at decoration time,
stamps a :class:`RouteMetadata` record on the decorated function under
the ``_ajolopy_route`` attribute, and returns the function unchanged.
The mount layer (``mount_routes``) walks marked methods and registers
them via AJ-15's ``add_route``.

Returning the function unchanged is deliberate — ``await
instance.list_users()`` still invokes the original coroutine, so unit
tests, ``@Eval`` runners, and internal callers can skip HTTP framing
entirely.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, cast

from ajolopy.stream.decorator import STREAM_META_ATTR

from .errors import RouteConfigError

_ROUTE_META_ATTR = "_ajolopy_route"

HttpVerb = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

# Express-style ``:id`` segments are rejected with a pointer to
# Starlette's ``{id}`` form. The pattern matches a colon followed by a
# Python identifier inside a path segment.
_EXPRESS_PARAM_RE = re.compile(r"(^|/):[A-Za-z_][A-Za-z0-9_]*")

# Decorators wrap any callable shape — the route layer never inspects
# return types, leaving that to AJ-15's response serialiser.
F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class RouteMetadata:
    """Stamped on every route-decorated method.

    Held verbatim by ``mount_routes`` so route registration sees the
    exact values that the user wrote — no defaults are mutated or
    re-derived later.
    """

    method: HttpVerb
    path: str
    handler: Callable[..., Any]


def Get(path: str) -> Callable[[F], F]:  # noqa: N802 — public surface mirrors HTTP verbs.
    """Mark a method as a ``GET`` HTTP handler at ``path``."""
    return _make_decorator("GET", path)


def Post(path: str) -> Callable[[F], F]:  # noqa: N802 — public surface mirrors HTTP verbs.
    """Mark a method as a ``POST`` HTTP handler at ``path``."""
    return _make_decorator("POST", path)


def Put(path: str) -> Callable[[F], F]:  # noqa: N802 — public surface mirrors HTTP verbs.
    """Mark a method as a ``PUT`` HTTP handler at ``path``."""
    return _make_decorator("PUT", path)


def Patch(path: str) -> Callable[[F], F]:  # noqa: N802 — public surface mirrors HTTP verbs.
    """Mark a method as a ``PATCH`` HTTP handler at ``path``."""
    return _make_decorator("PATCH", path)


def Delete(path: str) -> Callable[[F], F]:  # noqa: N802 — public surface mirrors HTTP verbs.
    """Mark a method as a ``DELETE`` HTTP handler at ``path``."""
    return _make_decorator("DELETE", path)


def get_route_metadata(obj: object) -> RouteMetadata | None:
    """Return the :class:`RouteMetadata` stamped on ``obj``, or ``None``.

    Works for unbound functions, bound methods (the metadata lives on
    the underlying function, which Python exposes as ``__func__``), and
    any callable carrying the ``_ajolopy_route`` attribute.
    """
    metadata = getattr(obj, _ROUTE_META_ATTR, None)
    if metadata is None:
        func = getattr(obj, "__func__", None)
        if func is not None:
            metadata = getattr(func, _ROUTE_META_ATTR, None)
    return metadata if isinstance(metadata, RouteMetadata) else None


def iter_route_methods(target: object) -> Iterator[tuple[str, Any, RouteMetadata]]:
    """Yield ``(attr_name, bound_method, metadata)`` for every marked method.

    ``target`` may be a class or an instance. For classes, iteration
    walks the MRO; for instances, attribute access binds ``self``
    naturally. Class-level ``classmethod`` / ``staticmethod`` carrying
    route metadata are still discovered because the metadata is read
    from the underlying function.
    """
    cls = target if isinstance(target, type) else type(target)
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, attr in vars(klass).items():
            if name in seen:
                continue
            metadata = get_route_metadata(attr)
            if metadata is None:
                continue
            seen.add(name)
            bound = getattr(target, name)
            yield name, bound, metadata


# ----------------------------------------------------------------------- internals


def _make_decorator(method: HttpVerb, path: str) -> Callable[[F], F]:
    """Build the actual decorator closure for an HTTP verb."""
    _validate_path(method, path)

    def decorate(fn: F) -> F:
        existing_route = getattr(fn, _ROUTE_META_ATTR, None)
        if existing_route is not None:
            raise RouteConfigError(
                f"@{method.capitalize()} cannot be stacked on {_qualname(fn)}; "
                f"the method already carries route metadata "
                f"({existing_route.method} {existing_route.path!r}). "
                f"Declare a separate method per (method, path) pair."
            )
        if getattr(fn, STREAM_META_ATTR, None) is not None:
            raise RouteConfigError(
                f"@{method.capitalize()} cannot be applied to "
                f"{_qualname(fn)}: the method already carries @Stream "
                f"metadata. Use one of @Get/@Post/@Put/@Patch/@Delete "
                f"for non-streaming routes and @Stream for SSE — they "
                f"are mutually exclusive."
            )
        metadata = RouteMetadata(method=method, path=path, handler=fn)
        setattr(fn, _ROUTE_META_ATTR, metadata)
        return fn

    return decorate


def _qualname(obj: object) -> str:
    return getattr(obj, "__qualname__", repr(obj))


def _validate_path(method: HttpVerb, path: str) -> None:
    if not isinstance(path, str) or not path:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise RouteConfigError(f"@{method.capitalize()} path must be a non-empty string.")
    if not path.startswith("/"):
        raise RouteConfigError(f"@{method.capitalize()} path must start with '/'; got {path!r}.")
    if _EXPRESS_PARAM_RE.search(path) is not None:
        raise RouteConfigError(
            f"@{method.capitalize()} path {path!r} uses Express-style "
            f"':param' segments. Use Starlette's {{param}} form instead "
            f"(e.g. '/users/{{user_id}}')."
        )


# Re-export for static-type consumers (and the mount layer) that want
# the metadata attribute name without importing the private constant.
ROUTE_META_ATTR: str = _ROUTE_META_ATTR


# typing-only export — keeps ``F`` from being flagged as "unused" in __all__.
_ = cast("Any", F)
