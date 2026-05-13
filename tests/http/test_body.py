"""Tests for the ``Body()`` parameter marker and request-body parsing."""

from typing import Annotated, Any

from pydantic import BaseModel
from starlette.testclient import TestClient

from ajolopy.http import Body, add_route, create_app


class _Dto(BaseModel):
    name: str
    age: int


def test_body_basemodel_parses_and_validates_json():
    received: list[_Dto] = []

    async def handler(body: Annotated[_Dto, Body()]) -> dict[str, object]:
        received.append(body)
        return {"name": body.name, "age": body.age}

    app = create_app()
    add_route(app, "POST", "/x", handler)

    response = TestClient(app).post("/x", json={"name": "ada", "age": 30})

    assert response.status_code == 200
    assert response.json() == {"name": "ada", "age": 30}
    assert received[0].name == "ada"


def test_body_basemodel_validation_failure_returns_422():
    async def handler(body: Annotated[_Dto, Body()]) -> dict[str, object]:
        return {"unreachable": body.name}

    app = create_app()
    add_route(app, "POST", "/x", handler)

    response = TestClient(app).post("/x", json={"name": "ada", "age": "not-a-number"})

    assert response.status_code == 422
    body = response.json()
    assert body["statusCode"] == 422
    assert body["error"] == "Unprocessable Entity"
    assert body["message"] == "Validation failed"
    # `age` field failed → its loc appears in details.
    assert any("age" in str(detail.get("loc", ())) for detail in body["details"])


def test_body_invalid_json_returns_400():
    async def handler(body: Annotated[_Dto, Body()]) -> dict[str, object]:
        return {"unreachable": body.name}

    app = create_app()
    add_route(app, "POST", "/x", handler)

    response = TestClient(app).post(
        "/x", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Bad Request"


def test_body_bytes_receives_raw_payload():
    received: list[bytes] = []

    async def handler(body: Annotated[bytes, Body()]) -> dict[str, int]:
        received.append(body)
        return {"len": len(body)}

    app = create_app()
    add_route(app, "POST", "/x", handler)
    response = TestClient(app).post("/x", content=b"\x00\x01\x02 raw bytes")

    assert response.status_code == 200
    assert response.json() == {"len": 13}
    assert received[0] == b"\x00\x01\x02 raw bytes"


def test_body_str_decodes_utf8():
    received: list[str] = []

    async def handler(body: Annotated[str, Body()]) -> dict[str, str]:
        received.append(body)
        return {"echo": body}

    app = create_app()
    add_route(app, "POST", "/x", handler)

    response = TestClient(app).post("/x", content="hola — mundo".encode())

    assert response.status_code == 200
    assert response.json() == {"echo": "hola — mundo"}
    assert received[0] == "hola — mundo"


def test_body_dict_returns_parsed_json_without_validation():
    async def handler(body: Annotated[dict[str, Any], Body()]) -> dict[str, object]:
        return {"keys": sorted(body.keys()), "n": body.get("n")}

    app = create_app()
    add_route(app, "POST", "/x", handler)
    response = TestClient(app).post("/x", json={"n": 5, "x": "y"})

    assert response.status_code == 200
    assert response.json() == {"keys": ["n", "x"], "n": 5}
