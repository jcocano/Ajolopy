"""Wrap a Starlette endpoint with a guard chain.

The mount layers (``ajolopy.routes.mount_routes`` and
``ajolopy.stream.mount_streams``) call :func:`apply_guard_chain` with
the original endpoint callable plus the resolved guard chain. The
wrapper runs each guard sequentially BEFORE the endpoint body and
translates guard exceptions into the framework's HTTP envelope:

- :class:`GuardUnauthorizedError` → :class:`UnauthorizedException` (401).
- :class:`GuardForbiddenError` → :class:`ForbiddenException` (403).
- ``can_activate`` returning ``False`` without raising → 401 with a
  generic "Guard <Name> denied the request" message.
- Any other exception bubbles through to the existing AJ-15 filter
  pipeline (typically the catch-all 500).

The framework's existing JSON envelope
``{statusCode, error, message, details?}`` is reused — guards do NOT
ship their own response shape. The ``ajolopy.http.exceptions``
hierarchy already maps cleanly onto 401/403; the runtime simply raises
those exceptions and lets the registered ``DefaultHttpExceptionFilter``
serialise them.
"""

from typing import TYPE_CHECKING, Any

from ajolopy.http.exceptions import ForbiddenException, UnauthorizedException

from .decorator import get_guard_chain
from .errors import GuardForbiddenError, GuardUnauthorizedError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from starlette.requests import Request
    from starlette.responses import Response

    from .base import Guard


def apply_guard_chain(
    endpoint: Callable[[Request], Awaitable[Response]],
    guards: Sequence[Guard],
) -> Callable[[Request], Awaitable[Response]]:
    """Return a new endpoint that runs ``guards`` before ``endpoint``.

    The wrapper preserves the endpoint's calling convention exactly:
    one positional ``request`` argument, awaits a Starlette
    :class:`~starlette.responses.Response`. Guard rejection raises an
    :class:`HttpException`; the existing exception-filter pipeline
    converts that into the canonical JSON envelope.

    ``guards`` is captured by value (tuple-converted) so subsequent
    mutations of the caller's list do not affect already-mounted
    routes.
    """
    chain: tuple[Guard, ...] = tuple(guards)

    async def gated(request: Request) -> Response:
        for guard in chain:
            await _run_guard(guard, request)
        return await endpoint(request)

    return gated


async def _run_guard(guard: Guard, request: Request) -> None:
    """Execute a single guard, translating its outcome into HTTP terms."""
    try:
        passed: Any = await guard.can_activate(request)
    except GuardUnauthorizedError as exc:
        raise UnauthorizedException(str(exc) or "Authentication required.") from exc
    except GuardForbiddenError as exc:
        raise ForbiddenException(str(exc) or "Forbidden.") from exc
    if not passed:
        name = type(guard).__qualname__
        raise UnauthorizedException(f"Guard {name} denied the request.")


def resolve_guard_chain(host_class: type | None, handler: object) -> tuple[Guard, ...]:
    """Return the effective guard chain for ``(host_class, handler)``.

    Reads ``_ajolopy_guards`` from the host class first (so class-level
    guards run first), then from the bound method / underlying
    function. Either source may be empty; the concatenation is the
    final, immutable tuple stored on the mounted endpoint.

    ``host_class`` may be ``None`` when the mount layer does not know
    the host (e.g. an ad-hoc function added via ``add_route``). In that
    case only the handler-level metadata contributes.
    """
    class_guards = get_guard_chain(host_class) if host_class is not None else ()
    handler_guards = get_guard_chain(handler)
    return tuple(class_guards) + tuple(handler_guards)


__all__ = [
    "apply_guard_chain",
    "resolve_guard_chain",
]
