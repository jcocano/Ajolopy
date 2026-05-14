"""Public re-export surface for AJ-60."""

import ajolopy
from ajolopy.mcp_server import (
    MCPDependencyError,
    MCPServer,
    MCPServerConfigError,
    MCPServerError,
    MCPServerMetadata,
    MCPServerRuntime,
    MCPServerRuntimeError,
    ServerFactory,
    Transport,
    mount_mcp_servers,
)


class TestTopLevelExport:
    def test_top_level_exports_mcp_server(self) -> None:
        assert ajolopy.MCPServer is MCPServer

    def test_mcp_server_in_all(self) -> None:
        assert "MCPServer" in ajolopy.__all__


class TestPackageExports:
    def test_classes_exist(self) -> None:
        assert MCPServer is not None
        assert MCPServerError is not None
        assert MCPServerConfigError is not None
        assert MCPServerRuntimeError is not None
        assert MCPDependencyError is not None
        assert MCPServerMetadata is not None
        assert MCPServerRuntime is not None
        assert mount_mcp_servers is not None
        assert ServerFactory is not None
        assert Transport is not None

    def test_error_hierarchy(self) -> None:
        assert issubclass(MCPServerConfigError, MCPServerError)
        assert issubclass(MCPServerRuntimeError, MCPServerError)
        assert issubclass(MCPServerError, RuntimeError)

    def test_dependency_error_reused_from_consume_side(self) -> None:
        from ajolopy.mcp import MCPDependencyError as ConsumeMCPDependencyError

        # The publish side re-exports the same class; consumers can
        # ``except MCPDependencyError`` regardless of which package they
        # imported from.
        assert MCPDependencyError is ConsumeMCPDependencyError


class TestCreateAppSurface:
    def test_create_app_accepts_mcp_servers_kwarg(self) -> None:
        from ajolopy.http import create_app

        app_no_servers = create_app(mcp_servers=None)
        app_no_kwarg = create_app()
        assert len(app_no_servers.router.routes) == len(app_no_kwarg.router.routes)
