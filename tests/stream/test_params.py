"""``@Stream`` parameter resolution delegates to AJ-15's pipe."""

from collections.abc import AsyncGenerator
from typing import Annotated

from pydantic import BaseModel
from starlette.requests import Request
from starlette.testclient import TestClient

from ajolopy.http import Body, Header, Param, Query, create_app
from ajolopy.stream import Stream


class _Msg(BaseModel):
    message: str


def test_body_basemodel() -> None:
    class Host:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Msg, Body()]) -> AsyncGenerator[str]:
            yield body.message

    app = create_app(streams=[Host])
    with (
        TestClient(app) as client,
        client.stream("POST", "/chat", json={"message": "hello"}) as response,
    ):
        body = b"".join(response.iter_bytes())
    assert body == b"data: hello\n\n"


def test_body_validation_returns_422() -> None:
    class Host:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Msg, Body()]) -> AsyncGenerator[str]:
            yield body.message

    app = create_app(streams=[Host])
    with TestClient(app) as client:
        response = client.post("/chat", json={"other": "x"})
    assert response.status_code == 422


def test_query_param_on_get() -> None:
    class Host:
        @Stream("/chat", method="GET", heartbeat_seconds=None)
        async def respond(self, message: Annotated[str, Query()]) -> AsyncGenerator[str]:
            yield message

    app = create_app(streams=[Host])
    with (
        TestClient(app) as client,
        client.stream("GET", "/chat", params={"message": "hi"}) as response,
    ):
        body = b"".join(response.iter_bytes())
    assert body == b"data: hi\n\n"


def test_path_param() -> None:
    class Host:
        @Stream("/chat/{room}", heartbeat_seconds=None)
        async def respond(self, room: Annotated[str, Param()]) -> AsyncGenerator[str]:
            yield f"room={room}"

    app = create_app(streams=[Host])
    with TestClient(app) as client, client.stream("POST", "/chat/lobby") as response:
        body = b"".join(response.iter_bytes())
    assert body == b"data: room=lobby\n\n"


def test_header_param() -> None:
    class Host:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(
            self,
            body: Annotated[_Msg, Body()],
            authorization: Annotated[str, Header("authorization")],
        ) -> AsyncGenerator[str]:
            yield f"{authorization}:{body.message}"

    app = create_app(streams=[Host])
    with (
        TestClient(app) as client,
        client.stream(
            "POST",
            "/chat",
            json={"message": "hi"},
            headers={"authorization": "Bearer t"},
        ) as response,
    ):
        body = b"".join(response.iter_bytes())
    assert body == b"data: Bearer t:hi\n\n"


def test_raw_request_access() -> None:
    class Host:
        @Stream("/whoami", heartbeat_seconds=None)
        async def respond(self, request: Request) -> AsyncGenerator[str]:
            yield f"path={request.url.path}"

    app = create_app(streams=[Host])
    with TestClient(app) as client, client.stream("POST", "/whoami") as response:
        body = b"".join(response.iter_bytes())
    assert body == b"data: path=/whoami\n\n"
