"""Tests for ``create_app`` and ``add_route``.

Covers app construction, route registration, HTTP-verb validation, and
async/sync handler dispatch. Param markers, pipes, and filters are
exercised in their own per-concern files.
"""

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from ajolopy.http import HttpHandlerConfigError, add_route, create_app

if TYPE_CHECKING:
    from starlette.applications import Starlette


# --------------------------------------------------------------------- helpers


async def _ok_handler(_request: Request) -> dict[str, str]:
    return {"ok": "true"}


def _sync_handler(_request: Request) -> dict[str, str]:
    return {"ok": "sync"}


# --------------------------------------------------------------------- create_app


def test_create_app_returns_starlette_instance():
    from starlette.applications import Starlette

    app = create_app()
    assert isinstance(app, Starlette)


def test_create_app_starts_with_empty_routes():
    app = create_app()
    assert app.router.routes == []


def test_create_app_forwards_extra_routes_as_escape_hatch():
    async def raw_handler(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("raw")

    app = create_app(routes=[Route("/raw", raw_handler)])

    response = TestClient(app).get("/raw")
    assert response.status_code == 200
    assert response.text == "raw"


# --------------------------------------------------------------------- add_route


def test_add_route_registers_an_async_handler():
    app = create_app()
    add_route(app, "GET", "/ping", _ok_handler)

    response = TestClient(app).get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": "true"}


def test_add_route_accepts_method_in_any_case():
    app = create_app()
    add_route(app, "post", "/echo", _ok_handler)

    response = TestClient(app).post("/echo")
    assert response.status_code == 200


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_add_route_accepts_every_supported_verb(method: str):
    app = create_app()
    add_route(app, method, "/x", _ok_handler)

    response = TestClient(app).request(method, "/x")
    assert response.status_code == 200


def test_add_route_rejects_unknown_verb():
    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="BREW"):
        add_route(app, "BREW", "/teapot", _ok_handler)


def test_add_route_error_names_the_handler():
    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="_ok_handler"):
        add_route(app, "BOGUS", "/x", _ok_handler)


# --------------------------------------------------------------------- async vs sync


def test_async_handler_is_awaited_directly_without_to_thread():
    app = create_app()
    add_route(app, "GET", "/async", _ok_handler)

    with patch("ajolopy.http.app.asyncio.to_thread") as to_thread_mock:
        response = TestClient(app).get("/async")

    assert response.status_code == 200
    assert to_thread_mock.call_count == 0


def test_sync_handler_is_dispatched_via_to_thread():
    app = create_app()
    add_route(app, "GET", "/sync", _sync_handler)

    # Spy on asyncio.to_thread while keeping its real behaviour.
    import asyncio as real_asyncio

    with patch(
        "ajolopy.http.app.asyncio.to_thread",
        wraps=real_asyncio.to_thread,
    ) as to_thread_mock:
        response = TestClient(app).get("/sync")

    assert response.status_code == 200
    assert response.json() == {"ok": "sync"}
    assert to_thread_mock.call_count == 1


# --------------------------------------------------------------------- routes coexist


def test_add_route_and_escape_hatch_routes_coexist():
    async def raw_handler(_request: Request) -> JSONResponse:
        return JSONResponse({"raw": True})

    app: Starlette = create_app(routes=[Route("/raw", raw_handler)])
    add_route(app, "GET", "/framework", _ok_handler)

    client = TestClient(app)
    assert client.get("/raw").json() == {"raw": True}
    assert client.get("/framework").json() == {"ok": "true"}
