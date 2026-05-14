"""``mount_mcp_servers`` and ``create_app(mcp_servers=[...])`` for SSE."""

import pytest
from starlette.applications import Starlette

from ajolopy import MCPServer, Tool
from ajolopy.http import create_app
from ajolopy.mcp_server import MCPServerConfigError, mount_mcp_servers


@MCPServer(transport="sse", path="/mcp-sse")
class _SSE:
    @Tool
    def echo(self, value: str) -> str:
        return value


@MCPServer(transport="sse", path="/other-sse")
class _OtherSSE:
    @Tool
    def ping(self) -> str:
        return "pong"


class TestMountSSE:
    def test_mounts_get_and_post_routes(self) -> None:
        app = create_app()
        mount_mcp_servers(app, [_SSE])
        assert _route_exists(app, "/mcp-sse", "GET")
        assert _route_exists(app, "/mcp-sse/messages", "POST")

    def test_create_app_kwarg_mounts_sse(self) -> None:
        app = create_app(mcp_servers=[_SSE])
        assert _route_exists(app, "/mcp-sse", "GET")
        assert _route_exists(app, "/mcp-sse/messages", "POST")

    def test_overlapping_sse_paths_raise(self) -> None:
        @MCPServer(transport="sse", path="/mcp-sse")
        class _Collide:
            @Tool
            def x(self) -> str:
                return "x"

        app = create_app()
        with pytest.raises(MCPServerConfigError, match="route collision"):
            mount_mcp_servers(app, [_SSE, _Collide])

    def test_two_sse_servers_both_registered(self) -> None:
        app = create_app(mcp_servers=[_SSE, _OtherSSE])
        for path in ("/mcp-sse", "/other-sse"):
            assert _route_exists(app, path, "GET")
            assert _route_exists(app, f"{path}/messages", "POST")


def _route_exists(app: Starlette, path: str, method: str) -> bool:
    for route in app.router.routes:
        path_attr = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path_attr == path and methods is not None and method in methods:
            return True
    return False
