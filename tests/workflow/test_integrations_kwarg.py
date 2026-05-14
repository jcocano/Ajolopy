"""Cross-cut tests for ``@Workflow(integrations=[...])`` (the AJ-6 flip).

Verifies that the workflow runtime accepts ``integrations=`` instead
of rejecting it, that the kwarg form and the class-attribute form
behave identically, that the kwarg wins over the attribute, and that
MCP tools land in the coordinator's wire tool list.
"""

import logging
from typing import Any

import pytest

from ajolopy import Agent, Workflow
from ajolopy.mcp import MCP, ToolSchema, get_mcp_registry, reset_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.spec import Transport
from ajolopy.providers import register_provider
from tests.agent.conftest import FakeProvider
from tests.mcp.fakes import FakeMCPClient


@pytest.fixture
def two_agents() -> tuple[type, type]:
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="A")
    class _A:
        pass

    @Agent(model="claude-sonnet-4-7", system="B")
    class _B:
        pass

    return _A, _B


def _factory(by_spec: dict[str, FakeMCPClient]) -> Any:
    def f(spec: str, _t: Transport, _a: dict[str, Any] | None) -> MCPClient:
        return by_spec[spec]

    return f


def test_integrations_kwarg_no_longer_raises(two_agents: tuple[type, type]) -> None:
    a, b = two_agents
    reset_mcp_registry()

    @MCP(servers={"x": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Workflow(coordinator="claude-sonnet-4-7", agents=[a, b], integrations=[I])
    class _Team:
        pass

    assert _Team._workflow_runtime.integrations == [I]  # type: ignore[attr-defined]


def test_class_attribute_form_works(two_agents: tuple[type, type]) -> None:
    a, b = two_agents
    reset_mcp_registry()

    @MCP(servers={"x": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Workflow(coordinator="claude-sonnet-4-7", agents=[a, b])
    class _Team:
        integrations = [I]

    assert _Team._workflow_runtime.integrations == [I]  # type: ignore[attr-defined]


def test_kwarg_wins_with_info_log(two_agents: tuple[type, type], caplog: Any) -> None:
    a, b = two_agents
    reset_mcp_registry()

    @MCP(servers={"x": "stdio:cmd"})
    class I1:
        pass

    @MCP(servers={"y": "stdio:cmd"})
    class I2:
        pass

    with caplog.at_level(logging.INFO, logger="ajolopy.workflow"):

        @Workflow(coordinator="claude-sonnet-4-7", agents=[a, b], integrations=[I2])
        class _Team:
            integrations = [I1]

    assert _Team._workflow_runtime.integrations == [I2]  # type: ignore[attr-defined]
    assert any("kwarg wins" in r.message for r in caplog.records)


async def test_mcp_tools_surface_to_coordinator_and_agents(
    patch_client_builder: Any, two_agents: tuple[type, type]
) -> None:
    client = FakeMCPClient(
        canonical="stdio:cmd",
        tools=[ToolSchema(name="t", description="", input_schema={})],
    )
    patch_client_builder(_factory({"stdio:cmd": client}))
    a, b = two_agents

    @MCP(servers={"s": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Workflow(coordinator="claude-sonnet-4-7", agents=[a, b], integrations=[I])
    class _Team:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    _Team._workflow_runtime.wire_mcp_tools(registry)  # type: ignore[attr-defined]

    # Coordinator wire tool list includes the MCP tool.
    coord_names = [t.name for t in _Team._workflow_runtime._wire_tools]  # type: ignore[attr-defined]
    assert "s__t" in coord_names

    # And every delegated agent sees the same MCP tool in its wire tool list.
    for agent_cls in (a, b):
        wire = [t.name for t in agent_cls._agent_runtime._wire_tools]
        assert "s__t" in wire
