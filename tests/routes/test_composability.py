"""``@Stream`` and route decorators coexist on the same class."""

from collections.abc import AsyncGenerator

import pytest
from starlette.testclient import TestClient

from ajolopy.http import create_app
from ajolopy.routes import Get, mount_routes
from ajolopy.stream import Stream, mount_streams


class _Chatty:
    @Stream("/chat", heartbeat_seconds=None)
    async def chat(self) -> AsyncGenerator[str]:
        yield "hi"

    @Get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}


class TestStreamAndRoutesCoexist:
    def test_mount_routes_does_not_touch_stream_methods(self) -> None:
        app = create_app()
        mount_routes(app, [_Chatty])
        # Only the @Get route is mounted; @Stream is ignored by
        # mount_routes.
        assert _route_exists(app, "/health", "GET")
        assert not _route_exists(app, "/chat", "POST")

    def test_mount_streams_does_not_touch_route_methods(self) -> None:
        app = create_app()
        mount_streams(app, [_Chatty])
        assert _route_exists(app, "/chat", "POST")
        assert not _route_exists(app, "/health", "GET")

    def test_both_mount_helpers_register_their_respective_methods(self) -> None:
        app = create_app()
        mount_streams(app, [_Chatty])
        mount_routes(app, [_Chatty])
        assert _route_exists(app, "/chat", "POST")
        assert _route_exists(app, "/health", "GET")

    def test_both_endpoints_respond_end_to_end(self) -> None:
        app = create_app()
        mount_streams(app, [_Chatty])
        mount_routes(app, [_Chatty])
        with TestClient(app) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}

            with client.stream("POST", "/chat") as stream_response:
                assert stream_response.status_code == 200
                body = b"".join(stream_response.iter_bytes())
            assert body == b"data: hi\n\n"


@pytest.mark.asyncio
async def test_route_decorated_method_callable_directly() -> None:
    """Decorated method invoked from Python skips HTTP framing."""

    class Plain:
        @Get("/health")
        async def health(self) -> dict[str, str]:
            return {"status": "ok"}

    instance = Plain()
    result = await instance.health()
    assert result == {"status": "ok"}


def _route_exists(app: object, path: str, method: str) -> bool:
    router = getattr(app, "router", None)
    if router is None:
        return False
    for route in getattr(router, "routes", []):
        path_attr = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path_attr == path and methods is not None and method in methods:
            return True
    return False
