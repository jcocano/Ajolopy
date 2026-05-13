"""HTTP route decorators — method-level verbs and the class-level controller.

Public surface — the five HTTP verb decorators (``Get``, ``Post``,
``Put``, ``Patch``, ``Delete``), the class-level ``Controller``
decorator that stamps a shared path prefix, the ``mount_routes`` helper,
and the route- / controller-layer error hierarchies. The decorators
stamp metadata on the decorated callable / class (no wrapping);
``mount_routes`` walks marked methods, joins any ``@Controller`` prefix
to each method-level path, and forwards to AJ-15's ``add_route`` so
parameter injection (``Body`` / ``Query`` / ``Param`` / ``Header``) and
response serialisation come for free.
"""

from .controller import Controller, get_controller_prefix
from .decorator import (
    Delete,
    Get,
    Patch,
    Post,
    Put,
    RouteMetadata,
    get_route_metadata,
    iter_route_methods,
)
from .errors import (
    ControllerConfigError,
    ControllerError,
    RouteConfigError,
    RouteLayerError,
)
from .mount import mount_routes

__all__ = [
    "Controller",
    "ControllerConfigError",
    "ControllerError",
    "Delete",
    "Get",
    "Patch",
    "Post",
    "Put",
    "RouteConfigError",
    "RouteLayerError",
    "RouteMetadata",
    "get_controller_prefix",
    "get_route_metadata",
    "iter_route_methods",
    "mount_routes",
]
