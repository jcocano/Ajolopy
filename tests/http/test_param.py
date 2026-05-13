"""Tests for the ``Param()`` URL path placeholder marker."""

from typing import Annotated

import pytest
from starlette.testclient import TestClient

from ajolopy.http import HttpHandlerConfigError, Param, add_route, create_app


def test_param_str_reads_placeholder_of_same_name():
    async def handler(user_id: Annotated[str, Param()]) -> dict[str, str]:
        return {"user_id": user_id}

    app = create_app()
    add_route(app, "GET", "/users/{user_id}", handler)

    assert TestClient(app).get("/users/u_123").json() == {"user_id": "u_123"}


def test_param_int_coerces_captured_string():
    async def handler(user_id: Annotated[int, Param()]) -> dict[str, int]:
        return {"user_id": user_id}

    app = create_app()
    add_route(app, "GET", "/users/{user_id}", handler)

    assert TestClient(app).get("/users/42").json() == {"user_id": 42}


def test_param_int_non_numeric_capture_returns_422():
    async def handler(user_id: Annotated[int, Param()]) -> dict[str, int]:
        return {"user_id": user_id}

    app = create_app()
    add_route(app, "GET", "/users/{user_id}", handler)
    response = TestClient(app).get("/users/abc")

    assert response.status_code == 422


def test_param_name_override_reads_from_aliased_placeholder():
    async def handler(uid: Annotated[str, Param("user_id")]) -> dict[str, str]:
        return {"uid": uid}

    app = create_app()
    add_route(app, "GET", "/users/{user_id}", handler)

    assert TestClient(app).get("/users/abc").json() == {"uid": "abc"}


def test_param_with_no_matching_placeholder_raises_config_error():
    async def handler(uid: Annotated[str, Param()]) -> dict[str, str]:
        return {"uid": uid}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="uid"):
        add_route(app, "GET", "/users/{user_id}", handler)
