"""``@UseGuards`` composition with ``@MCPServer(transport="http" | "sse")``.

The decoration-time guards-on-stdio rejection lives in
``test_decorator_validation.py``. This module asserts the route-level
gating actually fires *before* the MCP protocol traffic when guards are
attached to an HTTP / SSE server.
"""

from starlette.testclient import TestClient

from ajolopy import MCPServer, Tool, UseGuards
from ajolopy.guards import BearerTokenGuard
from ajolopy.http import create_app


@UseGuards(BearerTokenGuard(token_env="API_TOKEN"))  # noqa: S106
@MCPServer(transport="http", path="/mcp")
class _Gated:
    @Tool
    def echo(self, value: str) -> str:
        return value


@UseGuards(BearerTokenGuard(token_env="API_TOKEN"))  # noqa: S106
@MCPServer(transport="sse", path="/mcp-sse")
class _GatedSSE:
    @Tool
    def echo(self, value: str) -> str:
        return value


class TestHttpGuardShortCircuit:
    def test_http_missing_token_returns_401(self, monkeypatch) -> None:
        monkeypatch.setenv("API_TOKEN", "expected-token")
        app = create_app(mcp_servers=[_Gated])
        with TestClient(app) as client:
            response = client.post("/mcp", content=b'{"jsonrpc":"2.0"}')
        # 401 = Unauthorized; the guard rejected the call before the
        # MCP session manager ever saw it.
        assert response.status_code == 401

    def test_http_wrong_token_returns_403(self, monkeypatch) -> None:
        monkeypatch.setenv("API_TOKEN", "expected-token")
        app = create_app(mcp_servers=[_Gated])
        with TestClient(app) as client:
            response = client.post(
                "/mcp",
                headers={"Authorization": "Bearer wrong"},
                content=b'{"jsonrpc":"2.0"}',
            )
        # 403 = Forbidden; the guard saw a token but rejected it.
        assert response.status_code == 403


class TestSSEGuardShortCircuit:
    def test_sse_get_missing_token_returns_401(self, monkeypatch) -> None:
        monkeypatch.setenv("API_TOKEN", "expected-token")
        app = create_app(mcp_servers=[_GatedSSE])
        with TestClient(app) as client:
            response = client.get("/mcp-sse")
        assert response.status_code == 401

    def test_sse_post_missing_token_returns_401(self, monkeypatch) -> None:
        monkeypatch.setenv("API_TOKEN", "expected-token")
        app = create_app(mcp_servers=[_GatedSSE])
        with TestClient(app) as client:
            response = client.post("/mcp-sse/messages", content=b'{"jsonrpc":"2.0"}')
        assert response.status_code == 401
