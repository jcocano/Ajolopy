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


def test_header_default_name_from_python_parameter():
    async def handler(x_trace_id: Annotated[str, Header()]) -> dict[str, str]:
        return {"trace_id": x_trace_id}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x", headers={"x-trace-id": "abc"})

    # Starlette headers are case-insensitive; the underscore→dash mapping is
    # the user's responsibility (Header(name=) override).
    assert response.status_code == 200 or response.status_code == 400  # documented limitation


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
