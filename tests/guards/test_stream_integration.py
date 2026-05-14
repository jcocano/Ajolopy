"""``@Stream`` integration: ``auth=True`` flip + guard chain wrapping."""

from collections.abc import AsyncGenerator
from typing import Any, override

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from ajolopy.guards import Guard, UseGuards
from ajolopy.guards.errors import GuardUnauthorizedError
from ajolopy.http import create_app
from ajolopy.stream import Stream, StreamConfigError, mount_streams


class _DenyGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        raise GuardUnauthorizedError("nope")


class _AllowGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        return True


class TestAuthTrueRequiresGuards:
    def test_no_guards_anywhere_raises_at_mount(self) -> None:
        class Chat:
            @Stream("/chat", auth=True)
            async def respond(self) -> AsyncGenerator[str]:
                yield "x"

        app = create_app()
        with pytest.raises(StreamConfigError, match="@UseGuards"):
            mount_streams(app, [Chat])


class TestAuthTrueWithHostGuard:
    def test_class_level_guard_mounts_cleanly(self) -> None:
        @UseGuards(_AllowGuard())
        class Chat:
            @Stream("/chat", auth=True)
            async def respond(self) -> AsyncGenerator[str]:
                yield "hello"

        app = create_app()
        mount_streams(app, [Chat])
        with TestClient(app) as client:
            response = client.post("/chat")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


class TestAuthTrueWithMethodGuard:
    def test_method_level_guard_mounts_cleanly(self) -> None:
        class Chat:
            @UseGuards(_AllowGuard())
            @Stream("/chat", auth=True)
            async def respond(self) -> AsyncGenerator[str]:
                yield "hello"

        app = create_app()
        mount_streams(app, [Chat])
        with TestClient(app) as client:
            response = client.post("/chat")
        assert response.status_code == 200


class TestStreamGuardRejectionIsJson:
    def test_rejection_is_json_not_sse(self) -> None:
        @UseGuards(_DenyGuard())
        class Chat:
            @Stream("/chat", auth=True)
            async def respond(self) -> AsyncGenerator[str]:
                yield "should-never-run"

        app = create_app()
        mount_streams(app, [Chat])
        with TestClient(app) as client:
            response = client.post("/chat")
        assert response.status_code == 401
        # No SSE headers were sent.
        assert response.headers["content-type"].startswith("application/json")
        body: dict[str, Any] = response.json()
        assert body["statusCode"] == 401


class TestAuthFalseWithGuards:
    def test_guards_still_run_when_auth_is_false(self) -> None:
        # @UseGuards is the load-bearing primitive — auth=True is only
        # the "did you remember?" assertion. With auth=False and a guard
        # on the method, the chain still gates the stream.
        @UseGuards(_DenyGuard())
        class Chat:
            @Stream("/chat", auth=False)
            async def respond(self) -> AsyncGenerator[str]:
                yield "x"

        app = create_app()
        mount_streams(app, [Chat])
        with TestClient(app) as client:
            response = client.post("/chat")
        assert response.status_code == 401
