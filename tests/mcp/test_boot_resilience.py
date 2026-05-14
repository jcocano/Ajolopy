"""Boot resilience: unhealthy servers must never abort the factory."""

from typing import Any

from ajolopy.mcp import MCP, ToolSchema, get_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.spec import Transport
from tests.mcp.fakes import FakeMCPClient


def _factory_from(map_: dict[str, FakeMCPClient]) -> Any:
    def factory(spec: str, _t: Transport, _a: dict[str, Any] | None) -> MCPClient:
        return map_[spec]

    return factory


async def test_connect_failure_marks_server_unhealthy(patch_client_builder: Any) -> None:
    clients = {
        "stdio:good": FakeMCPClient(
            canonical="stdio:good",
            tools=[ToolSchema(name="t", description="", input_schema={})],
        ),
        "stdio:bad": FakeMCPClient(
            canonical="stdio:bad",
            raise_on_connect=RuntimeError("boom"),
        ),
    }
    patch_client_builder(_factory_from(clients))

    @MCP(servers={"good": "stdio:good", "bad": "stdio:bad"})
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    tools = registry.tools_for(I)
    assert tools == [("good__t", ToolSchema(name="t", description="", input_schema={}))]


async def test_list_tools_failure_marks_server_unhealthy(patch_client_builder: Any) -> None:
    clients = {
        "stdio:cmd": FakeMCPClient(
            canonical="stdio:cmd",
            raise_on_list_tools=RuntimeError("list failed"),
        ),
    }
    patch_client_builder(_factory_from(clients))

    @MCP(servers={"x": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    assert registry.tools_for(I) == []


async def test_missing_env_var_marks_server_unhealthy(patch_client_builder: Any) -> None:
    # No client should be built — env validation fails first.
    called: dict[str, int] = {"factory": 0}

    def factory(_spec: str, _t: Transport, _a: dict[str, Any] | None) -> MCPClient:
        called["factory"] += 1
        return FakeMCPClient()

    patch_client_builder(factory)

    @MCP(
        servers={"x": "https://example.com/mcp"},
        auth={"x": {"token": "${THIS_VAR_NEVER_SET}"}},
    )
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    # Factory should not have been asked because env was missing.
    assert called["factory"] == 0
    assert registry.tools_for(I) == []


async def test_boot_succeeds_with_all_unhealthy(patch_client_builder: Any) -> None:
    clients = {
        "stdio:a": FakeMCPClient(canonical="stdio:a", raise_on_connect=RuntimeError("a")),
        "stdio:b": FakeMCPClient(canonical="stdio:b", raise_on_connect=RuntimeError("b")),
    }
    patch_client_builder(_factory_from(clients))

    @MCP(servers={"a": "stdio:a", "b": "stdio:b"})
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    assert registry.tools_for(I) == []
