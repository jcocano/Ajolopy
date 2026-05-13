"""HTTP method route decorators.

Public surface — the five HTTP verb decorators (``Get``, ``Post``,
``Put``, ``Patch``, ``Delete``), the ``mount_routes`` helper, and the
route-layer error hierarchy. The decorators stamp metadata on the
decorated method (no wrapping); ``mount_routes`` walks marked methods
and forwards each to AJ-15's ``add_route`` so parameter injection
(``Body`` / ``Query`` / ``Param`` / ``Header``) and response
serialisation come for free.
"""

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
from .errors import RouteConfigError, RouteLayerError
from .mount import mount_routes

__all__ = [
    "Delete",
    "Get",
    "Patch",
    "Post",
    "Put",
    "RouteConfigError",
    "RouteLayerError",
    "RouteMetadata",
    "get_route_metadata",
    "iter_route_methods",
    "mount_routes",
]
