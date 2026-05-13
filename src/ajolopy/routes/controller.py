"""``@Controller(prefix)`` — class-level path prefix for HTTP route binding.

Third of the framework's foundational decorators (alongside ``@Module``
and ``@Injectable``). Stamps a single attribute,
``__ajolopy_route_prefix__``, on the decorated class. The class body is
otherwise untouched — controllers are metadata containers around the
method-level route decorators (``@Get`` / ``@Post`` / ``@Put`` /
``@Patch`` / ``@Delete`` from AJ-16), not wrappers.

``mount_routes`` (AJ-16, extended in AJ-10) reads
``__ajolopy_route_prefix__`` and joins the prefix to each method-level
path before forwarding to AJ-15's ``add_route``. Classes without the
attribute keep the original AJ-16 behaviour (no prefix, method paths
used verbatim).
"""

from typing import TYPE_CHECKING, TypeVar

from .errors import ControllerConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

# Public attribute name stamped on the decorated class. Exposed at module
# level so ``mount_routes`` and external callers (introspection tools,
# tests) can reference the constant instead of repeating the literal.
CONTROLLER_PREFIX_ATTR: str = "__ajolopy_route_prefix__"

# Preserve the decorated class's identity for static type checkers — the
# decorator returns the same class object, so consumers should keep
# their narrow type instead of widening to ``type``.
_C = TypeVar("_C", bound=type)


def _normalise_prefix(prefix: str) -> str:
    """Strip trailing slashes from ``prefix``, leaving the rest intact.

    ``"/users"`` and ``"/users/"`` both normalise to ``"/users"``. The
    empty string stays empty (no implicit leading slash). A bare ``"/"``
    collapses to ``""`` so it cannot silently match every prefix-less
    route at mount time.
    """
    if prefix == "":
        return ""
    return prefix.rstrip("/")


def Controller(prefix: str) -> Callable[[_C], _C]:  # noqa: N802 — Brief locks the decorator name as ``Controller``
    """Mark a class as an HTTP controller with a path prefix.

    Stamps ``__ajolopy_route_prefix__`` on the class so
    :func:`ajolopy.routes.mount_routes` joins the (normalised) prefix
    to each method-level path before registering the route. The class
    itself is returned unchanged — ``@Controller`` does not wrap,
    subclass, or instrument the class beyond the single attribute.

    Parameters
    ----------
    prefix:
        Path prefix shared by every route the class declares. Must be
        a ``str``. Trailing slashes are stripped at decoration time, so
        ``@Controller("/users/")`` and ``@Controller("/users")``
        produce the same effective prefix. The empty string is legal
        and produces unprefixed routes — useful for the root
        controller of an app.

    Returns
    -------
    Callable[[type], type]
        A decorator that stamps the normalised prefix on the target
        class and returns it.

    Raises
    ------
    ControllerConfigError
        ``prefix`` is not a ``str`` (``@Controller(42)``,
        ``@Controller(None)``, etc.), or the target class has already
        been decorated with ``@Controller`` (detected via
        ``cls.__dict__``, so subclasses of a decorated parent are not
        rejected — they simply do not inherit the prefix).

    Examples
    --------
    .. code-block:: python

        @Controller("/users")
        class UsersController:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

            @Get("/{user_id}")
            async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
                return {"id": user_id}
    """
    if not isinstance(prefix, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        # Runtime guard — callers can pass anything despite the type
        # hint. Naming the offending value plus its type matches the
        # message shape used by ``@Module`` / ``@Injectable``.
        raise ControllerConfigError(
            f"@Controller(prefix={prefix!r}) must be a str, got {type(prefix).__name__}."
        )

    normalised = _normalise_prefix(prefix)

    def decorator(cls: _C) -> _C:
        # ``__ajolopy_route_prefix__`` is intentionally *not* inherited:
        # a subclass of an @Controller-decorated class must be
        # re-decorated to count as a controller. We detect
        # re-decoration by checking the class's own ``__dict__`` (not
        # ``getattr``, which would walk the MRO and reject a legitimate
        # ``class Child(Parent): ...`` where ``Parent`` is already a
        # controller). Mirrors ``@Module`` and ``@Injectable``.
        if CONTROLLER_PREFIX_ATTR in cls.__dict__:
            raise ControllerConfigError(
                f"@Controller re-applied to {cls.__qualname__}; the class "
                f"already carries a route prefix "
                f"({cls.__dict__[CONTROLLER_PREFIX_ATTR]!r})."
            )
        setattr(cls, CONTROLLER_PREFIX_ATTR, normalised)
        return cls

    return decorator


def get_controller_prefix(cls: type) -> str | None:
    """Return the prefix stamped by ``@Controller``, or ``None``.

    Reads from ``cls.__dict__`` so subclasses of a decorated parent are
    *not* treated as controllers — consistent with the no-inheritance
    rule the decorator enforces at stamp time.
    """
    if not isinstance(cls, type):  # pyright: ignore[reportUnnecessaryIsInstance]
        return None
    prefix = cls.__dict__.get(CONTROLLER_PREFIX_ATTR)
    return prefix if isinstance(prefix, str) else None
