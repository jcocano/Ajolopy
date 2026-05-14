"""Connection pool + shutdown + reset tests for :class:`MCPRegistry`."""

from typing import Any

from ajolopy.mcp import MCP, ToolSchema, get_mcp_registry, reset_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.spec import Transport
from tests.mcp.fakes import FakeMCPClient


async def test_pool_dedupes_canonical_specs(
    patch_client_builder: Any,
) -> None:
    """Two @MCP classes sharing a stdio spec → ONE child process."""
    instances: dict[str, FakeMCPClient] = {}

    def factory(spec_str: str, _transport: Transport, _auth: dict[str, Any] | None) -> MCPClient:
        client = instances.get(spec_str)
        if client is None:
            client = FakeMCPClient(
                canonical=spec_str,
                tools=[ToolSchema(name="t", description="d", input_schema={})],
            )
            instances[spec_str] = client
        return client

    patch_client_builder(factory)

    @MCP(servers={"x": "stdio:npx -y @mcp/x"})
    class _A:
        pass

    @MCP(servers={"y": "stdio:npx   -y   @mcp/x"})  # extra whitespace → same canonical
    class _B:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)

    # Only one underlying client was built — even though two @MCP classes
    # reference the same canonical spec.
    assert len(instances) == 1
    one_client = next(iter(instances.values()))
    assert one_client.connect_called == 1

    # Both classes see the same tool.
    tools_a = registry.tools_for(_A)
    tools_b = registry.tools_for(_B)
    assert tools_a == [("x__t", ToolSchema(name="t", description="d", input_schema={}))]
    assert tools_b == [("y__t", ToolSchema(name="t", description="d", input_schema={}))]


async def test_instance_clients_not_deduped() -> None:
    """Two instance entries → two connect() calls (no dedup)."""
    a = FakeMCPClient(canonical="custom://same", tools=[])
    b = FakeMCPClient(canonical="custom://same", tools=[])

    @MCP(servers={"a": a})
    class _A:
        pass

    @MCP(servers={"b": b})
    class _B:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)

    assert a.connect_called == 1
    assert b.connect_called == 1


async def test_shutdown_closes_every_client(patch_client_builder: Any) -> None:
    instances: list[FakeMCPClient] = []

    def factory(spec_str: str, _transport: Transport, _auth: dict[str, Any] | None) -> MCPClient:
        client = FakeMCPClient(canonical=spec_str)
        instances.append(client)
        return client

    patch_client_builder(factory)

    @MCP(servers={"a": "stdio:cmd-a"})
    class _A:
        pass

    @MCP(servers={"b": "stdio:cmd-b"})
    class _B:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    await registry.shutdown()

    assert len(instances) == 2
    assert all(c.aclose_called == 1 for c in instances)


def test_reset_replaces_singleton() -> None:
    old = get_mcp_registry()
    new = reset_mcp_registry()
    assert new is not old
    assert get_mcp_registry() is new


async def test_unhealthy_server_does_not_abort_boot(patch_client_builder: Any) -> None:
    """A connect() failure marks the server unhealthy but boot completes."""

    def factory(spec_str: str, _transport: Transport, _auth: dict[str, Any] | None) -> MCPClient:
        if "broken" in spec_str:
            return FakeMCPClient(
                canonical=spec_str,
                raise_on_connect=RuntimeError("connect failed"),
            )
        return FakeMCPClient(
            canonical=spec_str,
            tools=[ToolSchema(name="ok", description="", input_schema={})],
        )

    patch_client_builder(factory)

    @MCP(servers={"good": "stdio:good", "bad": "stdio:broken-cmd"})
    class _Mixed:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)

    tools = registry.tools_for(_Mixed)
    assert tools == [("good__ok", ToolSchema(name="ok", description="", input_schema={}))]
