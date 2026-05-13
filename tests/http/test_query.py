"""Tests for the ``Query()`` parameter marker."""

from typing import Annotated

from pydantic import BaseModel
from starlette.testclient import TestClient

from ajolopy.http import Query, add_route, create_app


class _PageDto(BaseModel):
    page: int = 1
    limit: int = 20


def test_query_basemodel_validates_query_string():
    async def handler(q: Annotated[_PageDto, Query()]) -> dict[str, int]:
        return {"page": q.page, "limit": q.limit}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x?page=3&limit=50")

    assert response.status_code == 200
    assert response.json() == {"page": 3, "limit": 50}


def test_query_basemodel_validation_failure_returns_422():
    class StrictDto(BaseModel):
        page: int

    async def handler(q: Annotated[StrictDto, Query()]) -> dict[str, int]:
        return {"page": q.page}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x?page=abc")

    assert response.status_code == 422
    assert response.json()["statusCode"] == 422


def test_query_int_coerces_string():
    async def handler(page: Annotated[int, Query()]) -> dict[str, int]:
        return {"page": page}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x?page=7").json() == {"page": 7}


def test_query_int_non_numeric_returns_422():
    async def handler(page: Annotated[int, Query()]) -> dict[str, int]:
        return {"page": page}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x?page=abc")

    assert response.status_code == 422


def test_query_name_override_reads_from_aliased_key():
    async def handler(page: Annotated[int, Query("p")]) -> dict[str, int]:
        return {"page": page}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x?p=9").json() == {"page": 9}


def test_query_optional_resolves_to_none_when_absent():
    async def handler(page: Annotated[int | None, Query()]) -> dict[str, object]:
        return {"page": page}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x").json() == {"page": None}
    assert TestClient(app).get("/x?page=4").json() == {"page": 4}


def test_query_list_collects_repeated_keys():
    async def handler(tag: Annotated[list[str], Query()]) -> dict[str, list[str]]:
        return {"tags": tag}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x?tag=a&tag=b&tag=c")

    assert response.status_code == 200
    assert response.json() == {"tags": ["a", "b", "c"]}


def test_query_with_default_resolves_to_default_when_absent():
    async def handler(page: Annotated[int, Query()] = 1) -> dict[str, int]:
        return {"page": page}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    assert TestClient(app).get("/x").json() == {"page": 1}
    assert TestClient(app).get("/x?page=5").json() == {"page": 5}
