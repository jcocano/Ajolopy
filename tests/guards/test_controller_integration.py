"""``@Controller`` route integration: short-circuit before the ValidationPipe."""

from typing import Annotated, Any, override

from pydantic import BaseModel
from starlette.requests import Request
from starlette.testclient import TestClient

from ajolopy.guards import Guard, UseGuards
from ajolopy.guards.errors import GuardUnauthorizedError
from ajolopy.http import Body, create_app
from ajolopy.routes import Controller, Get, Post, mount_routes


class _DenyGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        raise GuardUnauthorizedError("nope")


class _AllowGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        return True


class _CreateDto(BaseModel):
    name: str
    age: int


def _build_app(host: type) -> Any:
    app = create_app()
    mount_routes(app, [host])
    return app


class TestControllerShortCircuitsBeforePipe:
    def test_malformed_body_returns_401_not_422(self) -> None:
        @UseGuards(_DenyGuard())
        @Controller("/users")
        class Users:
            @Post("/")
            async def create(self, body: Annotated[_CreateDto, Body()]) -> dict[str, str]:
                return {"name": body.name}

        with TestClient(_build_app(Users)) as client:
            # Body is missing the required ``age`` — without the guard
            # this would be a 422 from the ValidationPipe. The guard
            # rejects first → 401.
            response = client.post("/users/", json={"name": "Alice"})
        assert response.status_code == 401


class TestMethodGuardShortCircuit:
    def test_method_guard_runs_before_handler(self) -> None:
        @Controller("/users")
        class Users:
            @UseGuards(_DenyGuard())
            @Get("/")
            async def list_users(self) -> dict[str, list[str]]:
                # Should never be reached.
                raise AssertionError("handler must not run")

        with TestClient(_build_app(Users)) as client:
            response = client.get("/users/")
        assert response.status_code == 401


class TestPerMethodGuardsDoNotBleed:
    def test_gated_method_rejects_ungated_method_passes(self) -> None:
        @Controller("/users")
        class Users:
            @UseGuards(_DenyGuard())
            @Get("/admin")
            async def admin(self) -> dict[str, str]:
                return {"role": "admin"}

            @Get("/public")
            async def public(self) -> dict[str, str]:
                return {"hello": "world"}

        app = _build_app(Users)
        with TestClient(app) as client:
            assert client.get("/users/admin").status_code == 401
            response = client.get("/users/public")
            assert response.status_code == 200
            assert response.json() == {"hello": "world"}


class TestClassGuardAndMethodGuardCompose:
    def test_class_runs_first(self) -> None:
        @UseGuards(_AllowGuard())
        @Controller("/x")
        class X:
            @UseGuards(_AllowGuard())
            @Get("/")
            async def index(self) -> dict[str, str]:
                return {"hi": "ok"}

        with TestClient(_build_app(X)) as client:
            response = client.get("/x/")
        assert response.status_code == 200
