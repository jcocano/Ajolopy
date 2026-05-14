"""Tool dispatch through ``MCPServerRuntime``."""

import json
from typing import override

import pytest

from ajolopy import MCPServer, Tool
from ajolopy.mcp_server import MCPServerRuntime
from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR
from ajolopy.mcp_server.runtime import stringify_tool_result


class TestStringifyResult:
    def test_string_passthrough(self) -> None:
        assert stringify_tool_result("plain") == "plain"

    def test_dict_json_encoded(self) -> None:
        out = stringify_tool_result({"a": 1, "b": "x"})
        assert json.loads(out) == {"a": 1, "b": "x"}

    def test_list_json_encoded(self) -> None:
        out = stringify_tool_result([1, 2, "x"])
        assert json.loads(out) == [1, 2, "x"]

    def test_unserialisable_falls_back_to_str(self) -> None:
        class Custom:
            @override
            def __str__(self) -> str:
                return "<custom>"

        # ``default=str`` handles most non-json values, so the str()
        # fallback only fires when even ``default=str`` raises -- rare
        # in practice but covered for symmetry with the agent runtime.
        assert stringify_tool_result(Custom()) == json.dumps("<custom>")


@MCPServer(transport="stdio")
class _Counter:
    """Shared host class for the dispatch tests."""

    def __init__(self) -> None:
        self.calls = 0

    @Tool
    def increment(self, by: int = 1) -> int:
        """Increment the internal counter and return its new value."""
        self.calls += by
        return self.calls

    @Tool
    async def async_double(self, value: int) -> int:
        return value * 2

    @Tool
    def echo_obj(self) -> dict[str, int]:
        return {"value": self.calls}

    @Tool
    def boom(self) -> str:
        raise RuntimeError("boom failure")


def _runtime() -> MCPServerRuntime:
    meta = getattr(_Counter, MCP_SERVER_META_ATTR)
    return MCPServerRuntime(meta)


class TestDispatch:
    async def test_sync_tool_dispatch_returns_text_content(self) -> None:
        runtime = _runtime()
        result = await runtime.dispatch_tool("increment", {"by": 2})
        assert result.isError is False
        assert len(result.content) == 1
        assert result.content[0].text == "2"

    async def test_async_tool_dispatch(self) -> None:
        runtime = _runtime()
        result = await runtime.dispatch_tool("async_double", {"value": 7})
        assert result.isError is False
        assert result.content[0].text == "14"

    async def test_dict_result_json_encoded(self) -> None:
        runtime = _runtime()
        await runtime.dispatch_tool("increment", {"by": 3})
        result = await runtime.dispatch_tool("echo_obj", {})
        assert result.isError is False
        assert json.loads(result.content[0].text) == {"value": 3}

    async def test_unknown_tool_returns_error_result(self) -> None:
        runtime = _runtime()
        result = await runtime.dispatch_tool("does_not_exist", {})
        assert result.isError is True
        assert "Unknown tool" in result.content[0].text

    async def test_argument_validation_returns_error_result(self) -> None:
        runtime = _runtime()
        # `value` is required + int; passing non-int produces a Pydantic
        # ValidationError that we surface as isError=True.
        result = await runtime.dispatch_tool("async_double", {"value": "not-an-int"})
        assert result.isError is True
        assert "Invalid arguments" in result.content[0].text

    async def test_tool_exception_returns_error_result(self) -> None:
        runtime = _runtime()
        result = await runtime.dispatch_tool("boom", {})
        assert result.isError is True
        assert "boom failure" in result.content[0].text

    async def test_state_shared_across_calls(self) -> None:
        runtime = _runtime()
        await runtime.dispatch_tool("increment", {"by": 1})
        await runtime.dispatch_tool("increment", {"by": 4})
        result = await runtime.dispatch_tool("increment", {"by": 0})
        assert result.content[0].text == "5"

    async def test_pre_built_instance_is_bound(self) -> None:
        meta = getattr(_Counter, MCP_SERVER_META_ATTR)
        instance = _Counter()
        instance.calls = 42
        runtime = MCPServerRuntime(meta, instance=instance)
        result = await runtime.dispatch_tool("increment", {"by": 1})
        assert result.content[0].text == "43"


class TestRuntimeRequiredInit:
    async def test_required_args_at_dispatch_raises(self) -> None:
        # We can't decorate a class with required-arg __init__ (the
        # decorator already rejects it). For runtime-level coverage we
        # construct an MCPServerMetadata pointing at such a class manually
        # via direct ``__class__`` swap is awkward; instead exercise the
        # mount-time check via ``MCPServerRuntime._instantiate_host`` by
        # building metadata with a stripped original_cls.
        from ajolopy.agent.tool import discover_tools
        from ajolopy.mcp_server import MCPServerConfigError
        from ajolopy.mcp_server.metadata import MCPServerMetadata

        class Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Tool
            def x(self) -> str:
                return "ok"

        bindings, _ = discover_tools(Needs, None)
        meta = MCPServerMetadata(
            transport="stdio",
            path=None,
            name="needs",
            version="0.0.0",
            instructions=None,
            bindings=tuple(bindings),
            server_factory=None,
            original_cls=Needs,
        )
        runtime = MCPServerRuntime(meta)
        with pytest.raises(MCPServerConfigError, match="requires constructor argument 'db'"):
            _ = runtime.instance


class TestListTools:
    async def test_list_tools_matches_wire_shape(self) -> None:
        runtime = _runtime()
        handler = runtime._build_list_tools_handler()
        tools = await handler()
        names = {t.name for t in tools}
        assert names == {"increment", "async_double", "echo_obj", "boom"}
        # Schema mirrors the agent runtime's wire shape.
        increment_tool = next(t for t in tools if t.name == "increment")
        assert increment_tool.inputSchema["type"] == "object"
        assert "by" in increment_tool.inputSchema["properties"]
