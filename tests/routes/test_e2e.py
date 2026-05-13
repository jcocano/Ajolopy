"""End-to-end registration through Starlette's ``TestClient``."""

from typing import Annotated, Any

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from ajolopy.http import Body, Param, Query, create_app
from ajolopy.routes import Delete, Get, Patch, Post, Put, mount_routes


class _CreateUserDto(BaseModel):
    email: str
    name: str


class _UpdateUserDto(BaseModel):
    name: str


class _Users:
    @Get("/users")
    async def list_users(self, page: Annotated[int, Query()] = 1) -> dict[str, object]:
        return {"page": page, "items": []}

    @Get("/users/{user_id}")
    async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
        return {"id": user_id}

    @Post("/users")
    async def create_user(self, body: Annotated[_CreateUserDto, Body()]) -> dict[str, str]:
        return {"id": "u_1", "email": body.email, "name": body.name}

    @Delete("/users/{user_id}")
    async def delete_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
        return {"deleted": user_id}


def _build_app() -> Any:
    app = create_app()
    mount_routes(app, [_Users])
    return app


class TestGet:
    def test_returns_dict_as_json(self) -> None:
        with TestClient(_build_app()) as client:
            response = client.get("/users")
        assert response.status_code == 200
        assert response.json() == {"page": 1, "items": []}

    def test_query_parameter_forwarded(self) -> None:
        with TestClient(_build_app()) as client:
            response = client.get("/users", params={"page": "3"})
        assert response.status_code == 200
        assert response.json() == {"page": 3, "items": []}

    def test_path_parameter_forwarded(self) -> None:
        with TestClient(_build_app()) as client:
            response = client.get("/users/u_42")
        assert response.status_code == 200
        assert response.json() == {"id": "u_42"}


class TestPost:
    def test_body_parsed_through_validation_pipe(self) -> None:
        with TestClient(_build_app()) as client:
            response = client.post("/users", json={"email": "a@b.c", "name": "Alice"})
        assert response.status_code == 200
        assert response.json() == {
            "id": "u_1",
            "email": "a@b.c",
            "name": "Alice",
        }

    def test_invalid_body_returns_422_envelope(self) -> None:
        with TestClient(_build_app()) as client:
            response = client.post("/users", json={"email": "a@b.c"})
        # AJ-15's validation filter shape: 422 with a JSON envelope.
        assert response.status_code == 422
        payload = response.json()
        # The envelope has at least an ``error`` or ``detail`` key —
        # accept either to avoid coupling to AJ-15's exact wording.
        assert isinstance(payload, dict)
        assert payload  # non-empty


class TestDelete:
    def test_delete_with_path_param(self) -> None:
        with TestClient(_build_app()) as client:
            response = client.delete("/users/u_99")
        assert response.status_code == 200
        assert response.json() == {"deleted": "u_99"}


@pytest.mark.parametrize(
    ("decorator", "http_method"),
    [
        (Put, "PUT"),
        (Patch, "PATCH"),
        (Delete, "DELETE"),
    ],
)
def test_put_patch_delete_with_body(
    decorator: Any,
    http_method: str,
) -> None:
    """``Put`` / ``Patch`` / ``Delete`` end-to-end with a Pydantic body."""

    class Items:
        @decorator("/items/{item_id}")
        async def handler(
            self,
            item_id: Annotated[str, Param()],
            body: Annotated[_UpdateUserDto, Body()],
        ) -> dict[str, str]:
            return {"id": item_id, "name": body.name}

    app = create_app()
    mount_routes(app, [Items])
    with TestClient(app) as client:
        # ``TestClient.delete`` does not accept ``json=`` directly, so
        # we go through the generic ``request`` API for symmetry across
        # the three verbs.
        response = client.request(http_method, "/items/x_1", json={"name": "fresh"})
    assert response.status_code == 200
    assert response.json() == {"id": "x_1", "name": "fresh"}


class _UserResponse(BaseModel):
    id: str
    email: str


class _UsersModelReturn:
    @Get("/users-model")
    async def list_users(self) -> _UserResponse:
        return _UserResponse(id="u_1", email="a@b.c")


def test_basemodel_return_value_serialised() -> None:
    """Handlers returning a Pydantic model are serialised via AJ-15."""
    app = create_app()
    mount_routes(app, [_UsersModelReturn])
    with TestClient(app) as client:
        response = client.get("/users-model")
    assert response.status_code == 200
    assert response.json() == {"id": "u_1", "email": "a@b.c"}
