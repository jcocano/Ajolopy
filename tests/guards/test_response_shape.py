"""Guard rejection / error response shapes."""

from typing import Any, override

from starlette.requests import Request
from starlette.testclient import TestClient

from ajolopy.guards import Guard, UseGuards
from ajolopy.guards.errors import GuardForbiddenError, GuardUnauthorizedError
from ajolopy.http import create_app
from ajolopy.routes import Controller, Get, mount_routes


class _UnauthorizedGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        raise GuardUnauthorizedError("auth required")


class _ForbiddenGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        raise GuardForbiddenError("nope")


class _RaisingGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        raise ValueError("boom")


def _app_with(guard: Guard) -> Any:
    @UseGuards(guard)
    @Controller("/x")
    class X:
        @Get("/")
        async def y(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [X])
    return app


class TestEnvelope401:
    def test_body_uses_framework_envelope(self) -> None:
        with TestClient(_app_with(_UnauthorizedGuard())) as client:
            response = client.get("/x/")
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        # The framework envelope is ``{statusCode, error, message}`` —
        # the spec called for ``{"detail", "status"}`` but the existing
        # AJ-15 pipeline uses this shape; flipping it would break the
        # whole HTTP test suite, so the integration reuses the live
        # envelope. (See implementation report.)
        assert body["statusCode"] == 401
        assert body["error"] == "Unauthorized"
        assert body["message"] == "auth required"


class TestEnvelope403:
    def test_body_uses_framework_envelope(self) -> None:
        with TestClient(_app_with(_ForbiddenGuard())) as client:
            response = client.get("/x/")
        assert response.status_code == 403
        body = response.json()
        assert body["statusCode"] == 403
        assert body["error"] == "Forbidden"
        assert body["message"] == "nope"


class TestUnrelatedExceptionGives500:
    def test_value_error_falls_through_to_default_filter(self) -> None:
        # ``raise_server_exceptions=False`` so the TestClient does not
        # re-propagate the ValueError — the framework's catch-all
        # filter converts it to a 500 envelope.
        client = TestClient(_app_with(_RaisingGuard()), raise_server_exceptions=False)
        response = client.get("/x/")
        assert response.status_code == 500
        body = response.json()
        assert body["statusCode"] == 500
