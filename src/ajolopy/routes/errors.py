"""Framework-side errors raised by the route layer.

``RouteConfigError`` fires before traffic is served (decoration time or
mount time) — the user has misconfigured one of the method route
decorators or a ``mount_routes`` call. There is no runtime counterpart:
once an endpoint is registered the request flow is the same as any
other ``add_route`` handler, so request-time errors surface through the
shared HTTP exception filter pipeline (AJ-15).

``ControllerError`` / ``ControllerConfigError`` cover the class-level
``@Controller`` decorator (AJ-10). They form their own hierarchy
(rather than being subclasses of ``RouteLayerError``) so callers can
catch the controller-specific surface independently from the method
decorators while still ``isinstance``-checking against the framework's
common ``RuntimeError`` root.
"""


class RouteLayerError(RuntimeError):
    """Base class for any framework-side error raised by the route layer."""


class RouteConfigError(RouteLayerError):
    """A method route decorator or ``mount_routes`` call is invalid.

    Raised at decoration time for: empty / relative paths, Express-style
    ``:id`` segments (use Starlette's ``{id}`` form), stacked route
    decorators on the same method, and route decorators applied to a
    method already carrying ``@Stream`` metadata (or vice versa).

    Raised at mount time for: classes with required constructor
    arguments bound without a pre-built instance, classes with no
    route-marked methods, and duplicate ``(method, path)`` pairs across
    a single ``mount_routes`` call.
    """


class ControllerError(RuntimeError):
    """Base class for any framework-side error raised by ``@Controller`` (AJ-10)."""


class ControllerConfigError(ControllerError):
    """An ``@Controller(...)`` decoration is invalid.

    Raised at decoration time for: a non-string ``prefix`` argument
    (``@Controller(42)``, ``@Controller(None)``, etc.) and
    re-decoration of a class already carrying
    ``__ajolopy_route_prefix__``.
    """
