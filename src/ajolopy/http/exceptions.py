"""HTTP exceptions translated into responses by the framework's filters.

Concrete subclasses preset ``status`` for the canonical HTTP error codes.
``HttpException`` itself can also be raised directly with an ad-hoc
``status=`` to cover codes outside the preset hierarchy without forcing
the user to define a one-off subclass.

The default exception filter serialises any uncaught ``HttpException``
into the framework's JSON envelope::

    {
        "statusCode": <exc.status>,
        "error":      <canonical HTTP reason phrase>,
        "message":    <exc.message>,
        "details":    <exc.details>   # key omitted when details is None
    }
"""

from typing import override


class HttpException(Exception):  # noqa: N818  — NestJS-faithful naming, no -Error suffix
    """Base class for any exception that should become an HTTP response.

    Subclass with a class-level ``status`` to define a new HTTP error,
    or instantiate directly with ``status=`` for ad-hoc usage::

        raise HttpException("teapot", status=418)
        raise NotFoundException("user not found")
    """

    status: int = 500

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        details: object | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.details: object | None = details
        if status is not None:
            self.status = status

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status}, message={self.message!r})"


class BadRequestException(HttpException):
    """HTTP 400 — the request was malformed or contained invalid data."""

    status: int = 400


class UnauthorizedException(HttpException):
    """HTTP 401 — the request lacked valid authentication credentials."""

    status: int = 401


class ForbiddenException(HttpException):
    """HTTP 403 — the caller is authenticated but not permitted."""

    status: int = 403


class NotFoundException(HttpException):
    """HTTP 404 — the requested resource does not exist."""

    status: int = 404


class ConflictException(HttpException):
    """HTTP 409 — the request conflicts with the current resource state."""

    status: int = 409


class UnprocessableEntityException(HttpException):
    """HTTP 422 — the request was well-formed but semantically invalid."""

    status: int = 422


class InternalServerErrorException(HttpException):
    """HTTP 500 — an unexpected condition prevented handling the request."""

    status: int = 500
