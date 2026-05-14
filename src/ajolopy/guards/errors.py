"""Errors raised by ``@UseGuards`` and the guard runtime.

All errors derive from :class:`GuardError` so callers can catch the
whole family with a single ``except``. The hierarchy maps cleanly onto
HTTP semantics:

- :class:`GuardUnauthorizedError` — caller is not authenticated. The
  runtime maps the exception to HTTP 401 via the existing
  :class:`ajolopy.http.exceptions.UnauthorizedException` envelope.
- :class:`GuardForbiddenError` — caller is authenticated but the
  request is not permitted. Maps to HTTP 403 via
  :class:`ajolopy.http.exceptions.ForbiddenException`.
- :class:`UseGuardsConfigError` — the decorator was misconfigured at
  decoration / mount time. Raised by ``@UseGuards`` itself, not by a
  user's ``Guard.can_activate``.

The base class subclasses :class:`RuntimeError` so it is not
silently swallowed by ``except Exception`` style catch-alls in user
code that only expect domain exceptions.
"""


class GuardError(RuntimeError):
    """Base class for any error raised by the ``@UseGuards`` machinery."""


class GuardUnauthorizedError(GuardError):
    """Authentication is missing or invalid — maps to HTTP 401."""


class GuardForbiddenError(GuardError):
    """The caller is authenticated but not permitted — maps to HTTP 403."""


class UseGuardsConfigError(GuardError):
    """``@UseGuards`` was misconfigured at decoration or mount time.

    Raised eagerly so misuse surfaces at import / boot, never on the
    request-handling path.
    """


__all__ = [
    "GuardError",
    "GuardForbiddenError",
    "GuardUnauthorizedError",
    "UseGuardsConfigError",
]
