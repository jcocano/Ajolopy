"""Class-based exception filters and the default filter pipeline.

An ``ExceptionFilter`` is an async class whose ``catch`` method converts an
exception into a Starlette ``Response``. ``@Catch(SomeException)`` ties the
filter to one or more exception classes; ``create_app(exception_filters=
[...])`` wires it into the app's dispatch table.

The framework ships three defaults that are always registered first (so any
user filter targeting the same class wins on overlap):

- ``DefaultHttpExceptionFilter`` — serialises any ``HttpException`` into the
  ``{statusCode, error, message, details?}`` envelope.
- ``DefaultValidationErrorFilter`` — ``pydantic.ValidationError`` → 422 with
  ``details=exc.errors()``.
- ``DefaultExceptionFilter`` — catch-all 500 that logs the exception via the
  ``ajolopy.http`` logger and returns the no-leak envelope (no exception
  message in the body).

Dispatch is delegated to Starlette's exception middleware: it walks the
raised exception's MRO and picks the first registered handler. When two
filters declare ``@Catch`` on the same exception class, the later
registration wins (the registry dict overwrites in insertion order).
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeVar, cast, override

from pydantic import ValidationError
from starlette.responses import JSONResponse

from .errors import ExceptionFilterConfigError
from .exceptions import HttpException

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

_CATCH_ATTR = "__ajolopy_catches__"
_LOGGER = logging.getLogger("ajolopy.http")


class ExceptionFilter[E: BaseException](ABC):
    """Async class-based exception filter.

    Subclass, decorate with ``@Catch(*ExceptionClasses)``, and pass either
    the class itself or a pre-built instance into
    ``create_app(exception_filters=[...])``.
    """

    @abstractmethod
    async def catch(self, exc: E, request: Request) -> Response:
        """Convert ``exc`` raised under ``request`` into a Response."""


# Module-level TypeVar so the inner `_wrap` closure references a top-level
# name (matches the workaround used by ``agent/tool.py`` for CodeQL's
# PEP 695 flow analysis).
_F = TypeVar("_F", bound=type[Any])


def Catch(*exception_classes: type[BaseException]) -> Callable[[_F], _F]:  # noqa: N802
    """Register the decorated ``ExceptionFilter`` for one or more exceptions."""
    if not exception_classes:
        raise ExceptionFilterConfigError("@Catch() requires at least one exception class argument.")

    def _wrap(cls: _F) -> _F:
        if not issubclass(cls, ExceptionFilter):
            raise ExceptionFilterConfigError(
                f"@Catch can only decorate ExceptionFilter subclasses; got {cls!r}."
            )
        setattr(cls, _CATCH_ATTR, tuple(exception_classes))
        # Pyright narrows ``cls`` to ``type[ExceptionFilter[Unknown]]`` after
        # ``issubclass``; cast back so the decorator preserves the caller's
        # exact subclass type.
        return cast("_F", cls)

    return _wrap


def get_catches(filter_cls: type) -> tuple[type[BaseException], ...]:
    """Return the exception classes ``filter_cls`` was ``@Catch``-decorated for."""
    catches: object = getattr(filter_cls, _CATCH_ATTR, ())
    if isinstance(catches, tuple):
        # The attribute is only ever set by ``Catch`` (above), which writes
        # ``tuple[type[BaseException], ...]``; trust that contract here.
        return cast("tuple[type[BaseException], ...]", catches)
    return ()


# --------------------------------------------------------------------- helpers

# Stable reason phrases for the codes the framework emits. Hardcoded so the
# envelope matches NestJS's HttpException body (RFC 7231 wording) across
# Python versions — Python 3.13+ updated HTTPStatus(422).phrase from
# "Unprocessable Entity" (RFC 7231) to "Unprocessable Content" (RFC 9110),
# and we want the envelope to stay predictable.
_REASON_PHRASES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}


def _http_reason_phrase(status: int) -> str:
    if status in _REASON_PHRASES:
        return _REASON_PHRASES[status]
    from http import HTTPStatus

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def envelope(
    *,
    status: int,
    message: str,
    details: object | None = None,
) -> dict[str, object]:
    """Build the framework's canonical error envelope."""
    payload: dict[str, object] = {
        "statusCode": status,
        "error": _http_reason_phrase(status),
        "message": message,
    }
    if details is not None:
        payload["details"] = details
    return payload


# --------------------------------------------------------------------- default filters


@Catch(HttpException)
class DefaultHttpExceptionFilter(ExceptionFilter[HttpException]):
    """Serialise any ``HttpException`` into the JSON envelope."""

    @override
    async def catch(self, exc: HttpException, request: Request) -> Response:
        return JSONResponse(
            envelope(status=exc.status, message=exc.message, details=exc.details),
            status_code=exc.status,
        )


@Catch(ValidationError)
class DefaultValidationErrorFilter(ExceptionFilter[ValidationError]):
    """``pydantic.ValidationError`` → 422 with ``details=exc.errors()``."""

    @override
    async def catch(self, exc: ValidationError, request: Request) -> Response:
        return JSONResponse(
            envelope(status=422, message="Validation failed", details=exc.errors()),
            status_code=422,
        )


@Catch(Exception)
class DefaultExceptionFilter(ExceptionFilter[Exception]):
    """Catch-all: any uncaught exception → logged 500 with no-leak body."""

    @override
    async def catch(self, exc: Exception, request: Request) -> Response:
        _LOGGER.error(
            "Unhandled exception in HTTP handler",
            extra={"path": str(request.url.path), "method": request.method},
            exc_info=exc,
        )
        return JSONResponse(
            envelope(status=500, message="Internal Server Error"),
            status_code=500,
        )


# Default filters in registration order. Later entries take precedence on
# overlapping exception classes (as shipped, the three defaults target
# disjoint classes — they coexist rather than override).
DEFAULT_FILTERS: tuple[type[ExceptionFilter[Any]], ...] = (
    DefaultHttpExceptionFilter,
    DefaultValidationErrorFilter,
    DefaultExceptionFilter,
)
