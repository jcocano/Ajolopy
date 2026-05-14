"""Decoration-time validation for ``@MCPServer``."""

import pytest

from ajolopy import MCPServer, Tool, UseGuards
from ajolopy.guards import BearerTokenGuard
from ajolopy.mcp_server import MCPServerConfigError
from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR


class TestTransportValidation:
    def test_stdio_decorates_cleanly(self) -> None:
        @MCPServer(transport="stdio")
        class T:
            @Tool
            def lookup(self, order_id: str) -> dict[str, str]:
                return {"id": order_id}

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.transport == "stdio"
        assert meta.path is None
        # Class type is preserved for pyright / runtime users.
        assert T.__name__ == "T"

    def test_http_decorates_cleanly(self) -> None:
        @MCPServer(transport="http", path="/mcp")
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.transport == "http"
        assert meta.path == "/mcp"

    def test_sse_decorates_cleanly(self) -> None:
        @MCPServer(transport="sse", path="/mcp-sse")
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.transport == "sse"
        assert meta.path == "/mcp-sse"

    def test_unknown_transport_lists_accepted(self) -> None:
        with pytest.raises(MCPServerConfigError, match=r"stdio.*http.*sse"):

            @MCPServer(transport="bogus")  # type: ignore[arg-type]
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"


class TestPathValidation:
    def test_stdio_rejects_path(self) -> None:
        with pytest.raises(MCPServerConfigError, match="does not accept path"):

            @MCPServer(transport="stdio", path="/x")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_http_requires_path(self) -> None:
        with pytest.raises(MCPServerConfigError, match="requires a path"):

            @MCPServer(transport="http")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_http_path_without_leading_slash(self) -> None:
        with pytest.raises(MCPServerConfigError, match="must start with '/'"):

            @MCPServer(transport="http", path="no-leading-slash")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_http_path_with_bad_chars(self) -> None:
        with pytest.raises(MCPServerConfigError, match="must start with '/'"):

            @MCPServer(transport="http", path="/has spaces")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_sse_requires_path(self) -> None:
        with pytest.raises(MCPServerConfigError, match="requires a path"):

            @MCPServer(transport="sse")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"


class TestHostClassValidation:
    def test_no_tool_methods_raises(self) -> None:
        with pytest.raises(MCPServerConfigError, match="declares no @Tool methods"):

            @MCPServer(transport="stdio")
            class T:
                def helper(self) -> None:
                    pass

    def test_required_init_args_raises(self) -> None:
        with pytest.raises(MCPServerConfigError, match="requires constructor argument 'db'"):

            @MCPServer(transport="stdio")
            class T:
                def __init__(self, db: object) -> None:
                    self.db = db

                @Tool
                def x(self) -> str:
                    return "ok"

    def test_init_with_default_passes(self) -> None:
        @MCPServer(transport="stdio")
        class T:
            def __init__(self, db: object = None) -> None:
                self.db = db

            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert len(meta.bindings) == 1


class TestKwargValidation:
    def test_version_must_be_non_empty_string(self) -> None:
        with pytest.raises(MCPServerConfigError, match="version="):

            @MCPServer(transport="stdio", version="")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_name_must_be_non_empty_string(self) -> None:
        with pytest.raises(MCPServerConfigError, match="name="):

            @MCPServer(transport="stdio", name="")
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_instructions_must_be_str_or_none(self) -> None:
        with pytest.raises(MCPServerConfigError, match="instructions="):

            @MCPServer(transport="stdio", instructions=123)  # type: ignore[arg-type]
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_server_factory_must_be_callable(self) -> None:
        with pytest.raises(MCPServerConfigError, match="server_factory="):

            @MCPServer(transport="stdio", server_factory=42)
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_server_factory_callable_accepted(self) -> None:
        def factory(metadata: object, bindings: object) -> object:
            _ = (metadata, bindings)
            return object()

        @MCPServer(transport="stdio", server_factory=factory)
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.server_factory is factory


class TestUseGuardsComposition:
    def test_use_guards_below_stdio_raises_at_decoration(self) -> None:
        """``@UseGuards`` below ``@MCPServer(stdio)`` -- guards stamped first."""
        with pytest.raises(MCPServerConfigError, match="trust boundary"):

            @MCPServer(transport="stdio")
            @UseGuards(BearerTokenGuard(token_env="API_TOKEN"))  # noqa: S106
            class T:
                @Tool
                def x(self) -> str:
                    return "ok"

    def test_use_guards_with_http_decorates(self) -> None:
        @UseGuards(BearerTokenGuard(token_env="API_TOKEN"))  # noqa: S106
        @MCPServer(transport="http", path="/mcp")
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.transport == "http"
