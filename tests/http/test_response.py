"""Tests for handler return-value serialisation."""

from typing import TYPE_CHECKING

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.testclient import TestClient

from ajolopy.http import add_route, create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request


class _Item(BaseModel):
    id: str
    qty: int


def test_dict_return_becomes_json_response():
    async def handler(_request: Request) -> dict[str, int]:
        return {"qty": 5}

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"qty": 5}


def test_base_model_return_serialises_via_model_dump_json():
    async def handler(_request: Request) -> _Item:
        return _Item(id="abc", qty=3)

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 200
    assert response.json() == {"id": "abc", "qty": 3}


def test_response_subclass_is_forwarded_verbatim():
    async def handler(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("hello", status_code=201, headers={"x-foo": "bar"})

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 201
    assert response.headers["x-foo"] == "bar"
    assert response.text == "hello"


def test_streaming_response_is_forwarded_and_consumed_as_stream():
    chunks_yielded: list[bytes] = []

    async def body() -> AsyncIterator[bytes]:
        for piece in (b"first", b"second", b"third"):
            chunks_yielded.append(piece)
            yield piece

    async def handler(_request: Request) -> StreamingResponse:
        return StreamingResponse(body(), media_type="text/plain")

    app = create_app()
    add_route(app, "GET", "/stream", handler)

    with TestClient(app).stream("GET", "/stream") as response:
        collected = list(response.iter_raw())

    assert response.status_code == 200
    assert b"".join(collected) == b"firstsecondthird"
    assert chunks_yielded == [b"first", b"second", b"third"]


def test_none_return_produces_204():
    async def handler(_request: Request) -> None:
        return None

    app = create_app()
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x")

    assert response.status_code == 204
    assert response.content == b""


def test_unsupported_return_type_surfaces_as_500_with_no_leak():
    async def handler(_request: Request) -> int:
        return 42  # ints are not a documented return type.

    app = create_app()
    add_route(app, "GET", "/x", handler)
    # raise_server_exceptions=False: ServerErrorMiddleware re-raises after
    # running our handler so production servers log via Uvicorn; in tests we
    # just inspect the response.
    response = TestClient(app, raise_server_exceptions=False).get("/x")

    # The TypeError from _serialise_response is caught by the default
    # catch-all Exception filter; the body must not leak the underlying
    # message ("int" / "expected dict, BaseModel, ...").
    assert response.status_code == 500
    assert response.json() == {
        "statusCode": 500,
        "error": "Internal Server Error",
        "message": "Internal Server Error",
    }
    assert "int" not in response.text
    assert "dict" not in response.text
