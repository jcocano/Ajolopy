"""Cross-cut tests for ``@Agent(integrations=[...])`` and class-attribute form.

These tests live under ``tests/agent/`` because the surface they
exercise belongs to AJ-1 — they verify that the existing agent
runtime correctly accepts the new kwarg and resolves the kwarg-vs-class-
attribute precedence.
"""

import logging
from typing import Any

from ajolopy import Agent
from ajolopy.mcp import MCP, ToolSchema, get_mcp_registry, reset_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.spec import Transport
from tests.agent.conftest import FakeProvider
from tests.mcp.fakes import FakeMCPClient


def _factory(by_spec: dict[str, FakeMCPClient]) -> Any:
    def f(spec: str, _t: Transport, _a: dict[str, Any] | None) -> MCPClient:
        return by_spec[spec]

    return f


def test_class_attribute_form_is_accepted(
    monkeypatch: Any, register_fake_anthropic: type[FakeProvider]
) -> None:
    _ = register_fake_anthropic
    reset_mcp_registry()

    @MCP(servers={"x": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Agent(model="claude-opus-4-7", system="hi")
    class W:
        integrations = [I]

    runtime = W._agent_runtime  # type: ignore[attr-defined]
    assert runtime.integrations == [I]


def test_kwarg_form_is_accepted(register_fake_anthropic: type[FakeProvider]) -> None:
    _ = register_fake_anthropic
    reset_mcp_registry()

    @MCP(servers={"x": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Agent(model="claude-opus-4-7", system="hi", integrations=[I])
    class W:
        pass

    assert W._agent_runtime.integrations == [I]  # type: ignore[attr-defined]


def test_kwarg_wins_and_logs(register_fake_anthropic: type[FakeProvider], caplog: Any) -> None:
    _ = register_fake_anthropic
    reset_mcp_registry()

    @MCP(servers={"x": "stdio:cmd"})
    class I1:
        pass

    @MCP(servers={"y": "stdio:cmd"})
    class I2:
        pass

    with caplog.at_level(logging.INFO, logger="ajolopy.agent.runtime"):

        @Agent(model="claude-opus-4-7", system="hi", integrations=[I2])
        class W:
            integrations = [I1]

    assert W._agent_runtime.integrations == [I2]  # type: ignore[attr-defined]
    assert any("kwarg wins" in r.message for r in caplog.records)


async def test_kwarg_drives_tool_wiring(
    patch_client_builder: Any, register_fake_anthropic: type[FakeProvider]
) -> None:
    _ = register_fake_anthropic
    client = FakeMCPClient(
        canonical="stdio:cmd",
        tools=[ToolSchema(name="t", description="", input_schema={})],
    )
    patch_client_builder(_factory({"stdio:cmd": client}))

    @MCP(servers={"s": "stdio:cmd"})
    class I:  # noqa: E742
        pass

    @Agent(model="claude-opus-4-7", system="hi", integrations=[I])
    class W:
        pass

    registry = get_mcp_registry()
    await registry.connect_all_for(None)
    W._agent_runtime.wire_mcp_tools(registry)  # type: ignore[attr-defined]
    names = [t.name for t in W._agent_runtime._wire_tools]  # type: ignore[attr-defined]
    assert "s__t" in names
