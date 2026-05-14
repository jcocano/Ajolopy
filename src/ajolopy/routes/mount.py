"""Register route-decorated methods as Starlette routes.

``mount_routes(app, items)`` is the explicit two-line wiring path that
complements AJ-15's ``add_route``. AJ-10 adds the ``@Controller``
wrapper, which stamps ``__ajolopy_route_prefix__`` on a class so this
module knows to join the prefix to every method-level path before
forwarding to ``add_route``.

Each item is either a class (instantiated via ``Cls()``) or a pre-built
instance. Required constructor arguments raise :class:`RouteConfigError`
with guidance pointing to AJ-14 (full DI), which will lift the
zero-arg restriction.
"""

import inspect
from typing import TYPE_CHECKING

from ajolopy.guards.runtime import resolve_guard_chain
from ajolopy.http.app import add_route

from .controller import get_controller_prefix
from .decorator import iter_route_methods
from .errors import RouteConfigError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.applications import Starlette


def mount_routes(app: Starlette, items: Iterable[type | object]) -> None:
    """Walk every route-decorated method on ``items`` and register routes.

    Each marked method is forwarded to :func:`ajolopy.http.add_route`,
    so parameter resolution (``Body`` / ``Query`` / ``Param`` /
    ``Header``), pipe execution, and response serialisation all reuse
    AJ-15's machinery.

    For items whose class carries ``__ajolopy_route_prefix__`` (the
    ``@Controller`` stamp from AJ-10), the prefix is concatenated to
    each method-level path before registration. Items without the
    attribute keep the AJ-16 behaviour — method paths registered
    verbatim.

    Duplicate ``(method, path)`` pairs across all items raise
    :class:`RouteConfigError` so collisions surface at boot rather than
    silently shadowing routes.
    """
    items_list = list(items)
    instances = [_normalise(item) for item in items_list]

    seen: dict[tuple[str, str], str] = {}
    for instance in instances:
        cls = type(instance)
        cls_name = cls.__qualname__
        prefix = get_controller_prefix(cls) or ""
        marked = list(iter_route_methods(instance))
        if not marked:
            raise RouteConfigError(
                f"Class {cls_name!r} passed to mount_routes has no "
                f"@Get/@Post/@Put/@Patch/@Delete-marked methods. "
                f"Decorate at least one method or drop the class from "
                f"the list."
            )
        for _attr_name, bound_method, metadata in marked:
            full_path = _join_prefix(prefix, metadata.path)
            key = (metadata.method, full_path)
            existing = seen.get(key)
            new_qualname = metadata.handler.__qualname__
            if existing is not None:
                raise RouteConfigError(
                    f"Duplicate route {metadata.method} "
                    f"{full_path!r}: both {existing} and "
                    f"{new_qualname} declare it."
                )
            seen[key] = new_qualname

            # AJ-17: concatenate class-level + method-level @UseGuards
            # metadata; class guards always run first. Empty chain → no
            # wrapping (the add_route fast path takes over).
            guards = resolve_guard_chain(cls, bound_method)
            add_route(
                app,
                metadata.method,
                full_path,
                bound_method,
                guards=guards or None,
            )


def _join_prefix(prefix: str, path: str) -> str:
    """Concatenate ``prefix`` with the method-level ``path``.

    Join rules (mirrored in the spec and the test suite):

    - ``prefix=""`` + ``path="/users"`` → ``"/users"``.
    - ``prefix="/users"`` + ``path="/"`` → ``"/users/"`` — Starlette
      treats ``/users/`` and ``/users`` as distinct, so the trailing
      slash on the method path is preserved.
    - ``prefix="/users"`` + ``path="/{id}"`` → ``"/users/{id}"``.
    - ``prefix="/users"`` + ``path=""`` → ``"/users"``.

    Simple string concatenation — no slash deduplication beyond the
    trailing-slash strip the decorator already applied to ``prefix``.
    Double slashes inside the method path itself (``"/users//{id}"``)
    are the user's bug, not the mount layer's.
    """
    if prefix == "":
        return path
    return prefix + path


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
        raise RouteConfigError(
            f"mount_routes could not introspect {item.__qualname__}: {exc}. "
            f"Pass a pre-built instance: mount_routes(app, [{item.__name__}(...)])."
        ) from exc

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        is_required = param.default is inspect.Parameter.empty and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
        if is_required:
            raise RouteConfigError(
                f"Class {item.__qualname__} requires constructor argument "
                f"{name!r}. Pass a pre-built instance — "
                f"mount_routes(app, [{item.__name__}(...)]) — or wait "
                f"for AJ-14 (AjolopyFactory) to handle full DI."
            )

    try:
        return item()
    except Exception as exc:
        raise RouteConfigError(
            f"Failed to instantiate {item.__qualname__}() in mount_routes: "
            f"{exc}. Pass a pre-built instance or wait for AJ-14."
        ) from exc
