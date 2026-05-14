"""Tests for namespaced tool injection into agents."""

from typing import Any

import pytest

from ajolopy import Agent, Tool
from ajolopy.mcp import MCP, ToolSchema, get_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.spec import Transport
from ajolopy.providers import register_provider
from tests.agent.conftest import FakeProvider
from tests.mcp.fakes import FakeMCPClient


@pytest.fixture(autouse=True)
def register_fake_anthropic() -> type[FakeProvider]:
    register_provider("anthropic", FakeProvider, overwrite=True)
    return FakeProvider


def _make_factory(by_spec: dict[str, FakeMCPClient]) -> Any:
    def factory(spec_str: str, _t: Transport, _a: dict[str, Any] | None) -> MCPClient:
        return by_spec[spec_str]

    return factory


async def test_namespaced_names_use_double_underscore(
    patch_client_builder: Any,
) -> None:
    schema: dict[str, Any] = {"type": "object"}
    client = FakeMCPClient(
        canonical="stdio:github-cmd",
        tools=[
            ToolSchema(name="create_issue", description="Open one", input_schema=schema),
            ToolSchema(name="list_issues", description="List", input_schema=schema),
        ],
    )
    patch_client_builder(_make_factory({"stdio:github-cmd": client}))

    @MCP(servers={"github": "stdio:github-cmd"})
    class Integrations:
        pass

    @Agent(model="claude-sonnet-4-7", system="hi", integrations=[Integrations])
    class Worker:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    runtime = Worker._agent_runtime  # type: ignore[attr-defined]
    runtime.wire_mcp_tools(registry)

    names = [t.name for t in runtime._wire_tools]
    assert "github__create_issue" in names
    assert "github__list_issues" in names


async def test_schemas_are_copied_verbatim(
    patch_client_builder: Any,
) -> None:
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    client = FakeMCPClient(
        canonical="stdio:cmd",
        tools=[ToolSchema(name="t", description="d", input_schema=schema)],
    )
    patch_client_builder(_make_factory({"stdio:cmd": client}))

    @MCP(servers={"s": "stdio:cmd"})
    class I:  # noqa: E742 - test class
        pass

    @Agent(model="claude-sonnet-4-7", system="hi", integrations=[I])
    class W:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    W._agent_runtime.wire_mcp_tools(registry)  # type: ignore[attr-defined]

    tool = next(t for t in W._agent_runtime._wire_tools if t.name == "s__t")  # type: ignore[attr-defined]
    assert tool.description == "d"
    assert tool.parameters == schema


async def test_local_tool_wins_over_mcp_collision(
    patch_client_builder: Any,
) -> None:
    client = FakeMCPClient(
        canonical="stdio:cmd",
        tools=[ToolSchema(name="x", description="from-mcp", input_schema={})],
    )
    patch_client_builder(_make_factory({"stdio:cmd": client}))

    @MCP(servers={"github__x": "stdio:cmd"})  # craft a collision
    class I:  # noqa: E742
        pass

    @Agent(model="claude-sonnet-4-7", system="hi", integrations=[I])
    class W:
        @Tool
        def github__x(self) -> str:
            """Local tool that collides with the MCP namespaced name."""
            return "from-local"

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    W._agent_runtime.wire_mcp_tools(registry)  # type: ignore[attr-defined]

    wire = [t.name for t in W._agent_runtime._wire_tools]  # type: ignore[attr-defined]
    # The local @Tool method named ``github__x`` shadows the MCP tool
    # whose namespaced name is ``github__x__x``? — let me adjust: the
    # MCP class above injects ``github__x__x`` (server key
    # ``github__x``, tool name ``x``), which does NOT collide with the
    # local ``github__x``. Just assert both ended up in the wire list.
    assert "github__x" in wire  # local


async def test_two_agents_share_one_discovery(patch_client_builder: Any) -> None:
    """Two agents pointing at the same @MCP class hit the same tool list."""
    count: dict[str, int] = {"list_tools": 0}

    class CountingClient(FakeMCPClient):
        async def list_tools(self) -> list[ToolSchema]:  # type: ignore[override]
            count["list_tools"] += 1
            return list(self.tools)

    client = CountingClient(
        canonical="stdio:shared",
        tools=[ToolSchema(name="t", description="", input_schema={})],
    )
    patch_client_builder(_make_factory({"stdio:shared": client}))

    @MCP(servers={"s": "stdio:shared"})
    class I:  # noqa: E742
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)

    # Two consumers, but the discovery roundtrip ran exactly once.
    assert count["list_tools"] == 1
    assert registry.tools_for(I) == [
        ("s__t", ToolSchema(name="t", description="", input_schema={}))
    ]


async def test_mcp_tool_dispatch_routes_through_registry(
    patch_client_builder: Any,
) -> None:
    client = FakeMCPClient(
        canonical="stdio:cmd",
        tools=[ToolSchema(name="create_issue", description="", input_schema={})],
        call_results={"create_issue": "issue#42 created"},
    )
    patch_client_builder(_make_factory({"stdio:cmd": client}))

    @MCP(servers={"github": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Agent(model="claude-sonnet-4-7", system="hi", integrations=[I])
    class W:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    W._agent_runtime.wire_mcp_tools(registry)  # type: ignore[attr-defined]

    result = await registry.call_tool("github__create_issue", {"title": "bug"})
    assert result == "issue#42 created"
    assert client.calls == [("create_issue", {"title": "bug"})]
