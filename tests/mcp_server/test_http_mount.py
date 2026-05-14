"""``mount_mcp_servers`` and ``create_app(mcp_servers=[...])`` for HTTP."""

from unittest.mock import patch

import pytest
from starlette.applications import Starlette

from ajolopy import MCPServer, Tool
from ajolopy.http import create_app
from ajolopy.mcp_server import MCPServerConfigError, mount_mcp_servers


@MCPServer(transport="http", path="/mcp")
class _Tools:
    @Tool
    def echo(self, value: str) -> str:
        return value


@MCPServer(transport="http", path="/other")
class _Other:
    @Tool
    def ping(self) -> str:
        return "pong"


@MCPServer(transport="stdio")
class _StdioOnly:
    @Tool
    def ping(self) -> str:
        return "pong"


class TestMountHttp:
    def test_mounts_post_route(self) -> None:
        app = create_app()
        mount_mcp_servers(app, [_Tools])
        assert _route_exists(app, "/mcp", "POST")

    def test_create_app_kwarg_mounts(self) -> None:
        app = create_app(mcp_servers=[_Tools])
        assert _route_exists(app, "/mcp", "POST")

    def test_mcp_servers_none_leaves_app_unchanged(self) -> None:
        app_before = create_app()
        app_after = create_app(mcp_servers=None)
        assert len(app_after.router.routes) == len(app_before.router.routes)

    def test_pre_built_instance_is_not_reinstantiated(self) -> None:
        instance = _Tools()
        app = create_app()
        with patch.object(_Tools, "__init__", return_value=None) as init_spy:
            mount_mcp_servers(app, [instance])
            init_spy.assert_not_called()
        assert _route_exists(app, "/mcp", "POST")

    def test_overlapping_paths_raise(self) -> None:
        @MCPServer(transport="http", path="/mcp")
        class _Collide:
            @Tool
            def x(self) -> str:
                return "x"

        app = create_app()
        with pytest.raises(MCPServerConfigError, match="route collision"):
            mount_mcp_servers(app, [_Tools, _Collide])

    def test_required_init_raises_at_mount(self) -> None:
        class _Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Tool
            def x(self) -> str:
                return "ok"

        # We cannot @MCPServer-decorate Needs at decoration (rejected).
        # Build the metadata manually and stamp it to exercise the
        # mount-layer fallback.
        from ajolopy.agent.tool import discover_tools
        from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR
        from ajolopy.mcp_server.metadata import MCPServerMetadata

        bindings, _ = discover_tools(_Needs, None)
        meta = MCPServerMetadata(
            transport="http",
            path="/needs",
            name="needs",
            version="0.0.0",
            instructions=None,
            bindings=tuple(bindings),
            server_factory=None,
            original_cls=_Needs,
        )
        setattr(_Needs, MCP_SERVER_META_ATTR, meta)
        app = create_app()
        with pytest.raises(MCPServerConfigError, match="requires constructor argument 'db'"):
            mount_mcp_servers(app, [_Needs])

    def test_stdio_target_rejected_at_mount(self) -> None:
        app = create_app()
        with pytest.raises(MCPServerConfigError, match="ajolopy mcp-serve"):
            mount_mcp_servers(app, [_StdioOnly])

    def test_undecorated_target_rejected_at_mount(self) -> None:
        class _Plain:
            @Tool
            def x(self) -> str:
                return "ok"

        app = create_app()
        with pytest.raises(MCPServerConfigError, match="not decorated with @MCPServer"):
            mount_mcp_servers(app, [_Plain])

    def test_two_mcp_servers_both_registered(self) -> None:
        app = create_app(mcp_servers=[_Tools, _Other])
        assert _route_exists(app, "/mcp", "POST")
        assert _route_exists(app, "/other", "POST")


def _route_exists(app: Starlette, path: str, method: str) -> bool:
    for route in app.router.routes:
        path_attr = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path_attr == path and methods is not None and method in methods:
            return True
    return False
