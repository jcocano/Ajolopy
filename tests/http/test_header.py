"""Tests for the ``Header()`` parameter marker."""

from typing import Annotated

from starlette.testclient import TestClient

from ajolopy.http import Header, add_route, create_app


def test_header_str_reads_request_header_case_insensitively():
    async def handler(auth: Annotated[str, Header("authorization")]) -> dict[str, str]:
        return {"auth": auth}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x", headers={"Authorization": "Bearer t"})

    assert response.status_code == 200
    assert response.json() == {"auth": "Bearer t"}


def test_header_default_name_matches_python_parameter_verbatim():
    """Header() without ``name=`` uses the python identifier verbatim.

    No ``_``→``-`` auto-translation; for ``X-Trace-Id`` etc., the user
    must pass an explicit ``Header("x-trace-id")``. Keeps the mapping
    predictable and matches NestJS's literal header access.
    """

    async def handler(x: Annotated[str | None, Header()]) -> dict[str, object]:
        return {"x": x}

    app = create_app()
    add_route(app, "GET", "/x", handler)

    # Lower-case header named "x" — matches the python parameter name verbatim.
    response = TestClient(app).get("/x", headers={"x": "hello"})
    assert response.status_code == 200
    assert response.json() == {"x": "hello"}


def test_header_optional_resolves_to_none_when_absent():
    async def handler(auth: Annotated[str | None, Header("authorization")]) -> dict[str, object]:
        return {"auth": auth}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x").json() == {"auth": None}


def test_header_required_missing_returns_400():
    async def handler(auth: Annotated[str, Header("authorization")]) -> dict[str, str]:
        return {"auth": auth}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "Bad Request"
    assert "authorization" in body["message"].lower()
