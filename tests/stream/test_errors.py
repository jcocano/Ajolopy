"""Mid-stream error handling — final error event + logging."""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from ajolopy.http import Body, create_app
from ajolopy.stream import Stream


class _Msg(BaseModel):
    message: str


def test_exception_mid_stream_emits_error_event_last(caplog: pytest.LogCaptureFixture) -> None:
    class Boom:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Msg, Body()]) -> AsyncGenerator[str]:
            yield "tok-1"
            yield "tok-2"
            raise RuntimeError(f"db unreachable: {body.message}")

    caplog.set_level(logging.ERROR, logger="ajolopy.stream")
    app = create_app(streams=[Boom])
    with (
        TestClient(app) as client,
        client.stream("POST", "/chat", json={"message": "x"}) as response,
    ):
        assert response.status_code == 200
        body = b"".join(response.iter_bytes())

    assert body == (b'data: tok-1\n\ndata: tok-2\n\ndata: {"error":"db unreachable: x"}\n\n')
    assert any(
        record.name == "ajolopy.stream" and "db unreachable" in record.message
        for record in caplog.records
    )


def test_exception_before_first_yield_still_uses_sse_envelope() -> None:
    class BoomEarly:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Msg, Body()]) -> AsyncGenerator[str]:
            raise ValueError("boom")
            yield body.message  # type: ignore[unreachable]  # pragma: no cover

    app = create_app(streams=[BoomEarly])
    with (
        TestClient(app) as client,
        client.stream("POST", "/chat", json={"message": "x"}) as response,
    ):
        # Headers already sent (SSE), so the framework MUST surface the
        # error inside the stream rather than swap envelopes mid-flight.
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b"".join(response.iter_bytes())
    assert body == b'data: {"error":"boom"}\n\n'


def test_validation_error_uses_http_envelope_not_sse() -> None:
    class _Strict(BaseModel):
        count: int

    class Strict:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Strict, Body()]) -> AsyncGenerator[str]:
            yield str(body.count)

    app = create_app(streams=[Strict])
    with TestClient(app) as client:
        # ``count`` is not an int — Pydantic rejects before the stream starts.
        response = client.post("/chat", json={"count": "not-a-number"})
    assert response.status_code == 422
    # Pipe failed before SSE began: response is the regular JSON envelope.
    body = response.json()
    assert body["statusCode"] == 422
    assert "details" in body


def test_unsupported_yield_type_surfaces_as_error_event() -> None:
    class BadYield:
        @Stream("/chat", heartbeat_seconds=None)
        async def respond(self, body: Annotated[_Msg, Body()]) -> AsyncGenerator[object]:
            yield "ok"
            yield 42  # int — not str/dict/BaseModel

    app = create_app(streams=[BadYield])
    with (
        TestClient(app) as client,
        client.stream("POST", "/chat", json={"message": "x"}) as response,
    ):
        body = b"".join(response.iter_bytes())
    assert body.startswith(b"data: ok\n\n")
    assert b'data: {"error":' in body
    assert b"must yield str, dict, or BaseModel" in body
