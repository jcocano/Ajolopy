"""Tests for class-based exception filters and the default filter pipeline."""

import logging
from typing import TYPE_CHECKING, override

import pytest
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from ajolopy.http import (
    Catch,
    ConflictException,
    ExceptionFilter,
    ExceptionFilterConfigError,
    HttpException,
    NotFoundException,
    add_route,
    create_app,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


# --------------------------------------------------------------------- defaults


def test_default_http_exception_filter_serialises_envelope():
    async def handler(_request: Request) -> dict[str, str]:
        raise NotFoundException("user gone")

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 404
    assert response.json() == {
        "statusCode": 404,
        "error": "Not Found",
        "message": "user gone",
    }


def test_default_http_exception_filter_surfaces_details():
    async def handler(_request: Request) -> dict[str, str]:
        raise ConflictException("dup", details={"field": "email"})

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 409
    assert response.json() == {
        "statusCode": 409,
        "error": "Conflict",
        "message": "dup",
        "details": {"field": "email"},
    }


def test_default_validation_error_filter_returns_422():
    class _Dto(BaseModel):
        n: int

    async def handler(_request: Request) -> dict[str, str]:
        _Dto.model_validate({"n": "not-a-number"})
        return {"unreachable": "x"}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    body = response.json()
    assert response.status_code == 422
    assert body["statusCode"] == 422
    assert body["error"] == "Unprocessable Entity"
    assert body["message"] == "Validation failed"
    assert isinstance(body["details"], list)
    assert body["details"][0]["loc"] == ["n"]


def test_default_exception_filter_returns_500_without_leaking_message(
    caplog: pytest.LogCaptureFixture,
):
    async def handler(_request: Request) -> dict[str, str]:
        raise RuntimeError("sensitive internal detail")

    app = create_app()
    add_route(app, "GET", "/x", handler)

    # raise_server_exceptions=False so the TestClient does not re-propagate
    # the exception that ServerErrorMiddleware re-raises after running our
    # 500 handler (intentional Starlette design — Uvicorn logs the re-raise
    # in production; our test just inspects the response and our caplog).
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="ajolopy.http"):
        response = client.get("/x")

    assert response.status_code == 500
    body = response.json()
    assert body == {
        "statusCode": 500,
        "error": "Internal Server Error",
        "message": "Internal Server Error",
    }
    assert "sensitive internal detail" not in response.text
    # The exception is still logged so the operator can investigate.
    assert any("Unhandled exception" in rec.message for rec in caplog.records)
    assert any(
        rec.exc_info is not None and rec.exc_info[1].args == ("sensitive internal detail",)  # type: ignore[index]
        for rec in caplog.records
    )


# --------------------------------------------------------------------- user filters


def test_user_filter_overrides_default_for_specific_subclass_only():
    @Catch(NotFoundException)
    class CustomNotFoundFilter(ExceptionFilter[NotFoundException]):
        @override
        async def catch(self, exc: NotFoundException, request: Request) -> Response:
            return JSONResponse({"custom": exc.message}, status_code=404)

    async def missing(_request: Request) -> dict[str, str]:
        raise NotFoundException("user")

    async def conflict(_request: Request) -> dict[str, str]:
        raise ConflictException("dup")

    app = create_app(exception_filters=[CustomNotFoundFilter])
    add_route(app, "GET", "/missing", missing)
    add_route(app, "GET", "/conflict", conflict)

    client = TestClient(app)
    # Custom NotFoundException filter wins.
    assert client.get("/missing").json() == {"custom": "user"}
    # ConflictException still goes through the default HttpException filter.
    conflict_body = client.get("/conflict").json()
    assert conflict_body["statusCode"] == 409
    assert conflict_body["message"] == "dup"


def test_filter_dispatch_picks_most_specific_class_via_mro():
    @Catch(HttpException)
    class GenericHttpFilter(ExceptionFilter[HttpException]):
        @override
        async def catch(self, exc: HttpException, request: Request) -> Response:
            return JSONResponse({"from": "generic", "msg": exc.message}, status_code=exc.status)

    @Catch(NotFoundException)
    class SpecificNotFoundFilter(ExceptionFilter[NotFoundException]):
        @override
        async def catch(self, exc: NotFoundException, request: Request) -> Response:
            return JSONResponse({"from": "specific", "msg": exc.message}, status_code=404)

    async def handler(_request: Request) -> dict[str, str]:
        raise NotFoundException("gone")

    # GenericHttpFilter is more general, SpecificNotFoundFilter is more specific —
    # the specific one wins even though it's registered later (MRO walk picks the
    # nearest class first).
    app = create_app(exception_filters=[GenericHttpFilter, SpecificNotFoundFilter])
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x").json() == {"from": "specific", "msg": "gone"}


def test_catch_accepts_multiple_classes():
    @Catch(NotFoundException, ConflictException)
    class TwoClassFilter(ExceptionFilter[HttpException]):
        @override
        async def catch(self, exc: HttpException, request: Request) -> Response:
            return JSONResponse({"caught": type(exc).__name__}, status_code=exc.status)

    async def gone(_request: Request) -> dict[str, str]:
        raise NotFoundException("x")

    async def dup(_request: Request) -> dict[str, str]:
        raise ConflictException("y")

    app = create_app(exception_filters=[TwoClassFilter])
    add_route(app, "GET", "/gone", gone)
    add_route(app, "GET", "/dup", dup)

    client = TestClient(app)
    assert client.get("/gone").json() == {"caught": "NotFoundException"}
    assert client.get("/dup").json() == {"caught": "ConflictException"}


def test_last_registered_filter_wins_for_same_class():
    @Catch(NotFoundException)
    class FirstFilter(ExceptionFilter[NotFoundException]):
        @override
        async def catch(self, exc: NotFoundException, request: Request) -> Response:
            return JSONResponse({"order": "first"}, status_code=404)

    @Catch(NotFoundException)
    class SecondFilter(ExceptionFilter[NotFoundException]):
        @override
        async def catch(self, exc: NotFoundException, request: Request) -> Response:
            return JSONResponse({"order": "second"}, status_code=404)

    async def handler(_request: Request) -> dict[str, str]:
        raise NotFoundException("x")

    app = create_app(exception_filters=[FirstFilter, SecondFilter])
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x").json() == {"order": "second"}


def test_filter_instance_is_accepted_alongside_classes():
    @Catch(NotFoundException)
    class MyFilter(ExceptionFilter[NotFoundException]):
        @override
        async def catch(self, exc: NotFoundException, request: Request) -> Response:
            return JSONResponse({"stamp": self.stamp}, status_code=404)

        def __init__(self) -> None:
            self.stamp = "pre-built"

    instance = MyFilter()

    async def handler(_request: Request) -> dict[str, str]:
        raise NotFoundException("x")

    app = create_app(exception_filters=[instance])
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x").json() == {"stamp": "pre-built"}


# --------------------------------------------------------------------- negative cases


def test_catch_without_arguments_raises_config_error():
    with pytest.raises(ExceptionFilterConfigError, match="at least one"):

        @Catch()
        class _Bad(ExceptionFilter[Exception]):
            @override
            async def catch(self, exc: Exception, request: Request) -> Response:
                raise NotImplementedError


def test_catch_on_non_exception_filter_class_raises_config_error():
    with pytest.raises(ExceptionFilterConfigError, match="ExceptionFilter"):

        @Catch(NotFoundException)
        class _NotAFilter:  # not subclassing ExceptionFilter
            pass
