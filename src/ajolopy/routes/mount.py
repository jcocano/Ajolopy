"""Register route-decorated methods as Starlette routes.

``mount_routes(app, items)`` is the explicit two-line wiring path that
complements AJ-15's ``add_route``. AJ-10 will later add a
``@Controller`` wrapper plus a ``create_app(controllers=[...])`` kwarg;
until then, the user pairs ``create_app()`` with ``mount_routes(app, [...])``.

Each item is either a class (instantiated via ``Cls()``) or a pre-built
instance. Required constructor arguments raise :class:`RouteConfigError`
with guidance pointing to AJ-14 (full DI), which will lift the
zero-arg restriction.
"""

import inspect
from typing import TYPE_CHECKING

from ajolopy.http.app import add_route

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

    Duplicate ``(method, path)`` pairs across all items raise
    :class:`RouteConfigError` so collisions surface at boot rather than
    silently shadowing routes.
    """
    items_list = list(items)
    instances = [_normalise(item) for item in items_list]

    seen: dict[tuple[str, str], str] = {}
    for instance in instances:
        cls_name = type(instance).__qualname__
        marked = list(iter_route_methods(instance))
        if not marked:
            raise RouteConfigError(
                f"Class {cls_name!r} passed to mount_routes has no "
                f"@Get/@Post/@Put/@Patch/@Delete-marked methods. "
                f"Decorate at least one method or drop the class from "
                f"the list."
            )
        for _attr_name, bound_method, metadata in marked:
            key = (metadata.method, metadata.path)
            existing = seen.get(key)
            new_qualname = metadata.handler.__qualname__
            if existing is not None:
                raise RouteConfigError(
                    f"Duplicate route {metadata.method} "
                    f"{metadata.path!r}: both {existing} and "
                    f"{new_qualname} declare it."
                )
            seen[key] = new_qualname

            add_route(app, metadata.method, metadata.path, bound_method)


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
