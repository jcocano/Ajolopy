"""Tests for the ``mcp.call_tool`` / ``mcp.discover`` spans + cost roll-up."""

from typing import Any

import pytest

from ajolopy.mcp import MCP, ToolSchema, get_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.errors import MCPRuntimeError, MCPToolTimeoutError
from ajolopy.mcp.spec import Transport
from tests.mcp.fakes import FakeMCPClient


def _factory_from(map_: dict[str, FakeMCPClient]) -> Any:
    def factory(spec: str, _t: Transport, _a: dict[str, Any] | None) -> MCPClient:
        return map_[spec]

    return factory


async def test_call_tool_returns_text(patch_client_builder: Any) -> None:
    clients = {
        "stdio:cmd": FakeMCPClient(
            canonical="stdio:cmd",
            tools=[ToolSchema(name="t", description="", input_schema={})],
            call_results={"t": "value"},
        ),
    }
    patch_client_builder(_factory_from(clients))

    @MCP(servers={"s": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    # Mimic what AgentRuntime.wire_mcp_tools does for dispatch registration.
    for namespaced, _schema in registry.tools_for(I):
        server_key, _, raw_name = namespaced.partition("__")
        registry.register_dispatch(
            I,
            namespaced_name=namespaced,
            server_key=server_key,
            raw_name=raw_name,
        )

    assert await registry.call_tool("s__t", {"k": 1}) == "value"


async def test_timeout_raises_specific_error(patch_client_builder: Any) -> None:
    clients = {
        "stdio:cmd": FakeMCPClient(
            canonical="stdio:cmd",
            tools=[ToolSchema(name="slow", description="", input_schema={})],
            call_delay=1.0,  # exceeds the per-call timeout we set below
        ),
    }
    patch_client_builder(_factory_from(clients))

    @MCP(servers={"s": "stdio:cmd"}, timeout=0.05)
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    for namespaced, _schema in registry.tools_for(I):
        server_key, _, raw_name = namespaced.partition("__")
        registry.register_dispatch(
            I,
            namespaced_name=namespaced,
            server_key=server_key,
            raw_name=raw_name,
        )

    with pytest.raises(MCPToolTimeoutError):
        await registry.call_tool("s__slow", {})


async def test_server_error_wraps_runtime_error(patch_client_builder: Any) -> None:
    clients = {
        "stdio:cmd": FakeMCPClient(
            canonical="stdio:cmd",
            tools=[ToolSchema(name="t", description="", input_schema={})],
            call_results={"t": ValueError("server says no")},
        ),
    }
    patch_client_builder(_factory_from(clients))

    @MCP(servers={"s": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    for namespaced, _schema in registry.tools_for(I):
        server_key, _, raw_name = namespaced.partition("__")
        registry.register_dispatch(
            I,
            namespaced_name=namespaced,
            server_key=server_key,
            raw_name=raw_name,
        )

    with pytest.raises(MCPRuntimeError, match="server says no"):
        await registry.call_tool("s__t", {})


def test_span_name_helpers_match_convention() -> None:
    from ajolopy.observability import mcp_call_tool_span_name, mcp_discover_span_name

    assert mcp_call_tool_span_name("github", "create_issue") == "mcp.call_tool github/create_issue"
    assert mcp_discover_span_name("github") == "mcp.discover github"
