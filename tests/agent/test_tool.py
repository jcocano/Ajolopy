"""Tests for the ``@Tool`` decorator + schema synthesis + discovery.

Covers the "Decorator basics", "Schema generation" and "Discovery by
``@Agent``" acceptance groups of ``specs/tool.md``. Loop-level behaviour
(execution, error surfacing, max-iteration cap) lives in
``test_tool_loop.py``.
"""

from typing import TYPE_CHECKING, Literal

import pytest
from pydantic import BaseModel, Field

from ajolopy import Agent, Tool
from ajolopy.agent import AgentConfigError, ToolDefinitionError
from ajolopy.agent.tool import _TOOL_MARKER, ToolMetadata

if TYPE_CHECKING:
    from .conftest import FakeProvider

# ---------------------------------------------------------------------------
# Decorator basics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_tool_preserves_async_method_callability() -> None:
    class Holder:
        @Tool
        async def echo(self, value: str) -> str:
            """Echo the value back."""
            return value

    h = Holder()
    assert await h.echo("hi") == "hi"


def test_bare_tool_preserves_sync_method_callability() -> None:
    class Holder:
        @Tool
        def upper(self, value: str) -> str:
            """Uppercase the value."""
            return value.upper()

    assert Holder().upper("hi") == "HI"


def test_tool_kwargs_override_name_and_description() -> None:
    class Holder:
        @Tool(name="upper_case", description="Custom override.")
        def upper(self, value: str) -> str:
            """Docstring that should be ignored."""
            return value.upper()

    metadata = getattr(Holder.upper, _TOOL_MARKER)
    assert isinstance(metadata, ToolMetadata)
    assert metadata.name == "upper_case"
    assert metadata.description == "Custom override."


def test_methods_without_tool_are_not_exposed(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool
        def used(self, x: int) -> int:
            """Used."""
            return x

        def ignored(self, x: int) -> int:
            return x

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert runtime.tool_names == ["used"]


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------


def _get_metadata(method: object) -> ToolMetadata:
    metadata = getattr(method, _TOOL_MARKER, None)
    assert isinstance(metadata, ToolMetadata)
    return metadata


def test_schema_from_signature_marks_required_and_types() -> None:
    class Holder:
        @Tool
        def lookup(self, order_id: str) -> str:
            """Look up an order."""
            return order_id

    schema = _get_metadata(Holder.lookup).json_schema()
    assert schema["type"] == "object"
    assert schema["properties"]["order_id"]["type"] == "string"
    assert schema["required"] == ["order_id"]


def test_schema_omits_required_for_defaulted_params() -> None:
    class Holder:
        @Tool
        def list_items(self, limit: int = 10) -> list[int]:
            """List up to ``limit`` items."""
            return list(range(limit))

    schema = _get_metadata(Holder.list_items).json_schema()
    assert "limit" in schema["properties"]
    assert schema.get("required", []) == []


def test_schema_handles_primitive_and_container_types() -> None:
    class Holder:
        @Tool
        def mixed(
            self,
            s: str,
            i: int,
            f: float,
            b: bool,
            xs: list[str],
            tags: dict[str, int],
            maybe: str | None = None,
        ) -> None:
            """Mixed-type tool."""
            return

    schema = _get_metadata(Holder.mixed).json_schema()
    props = schema["properties"]
    assert props["s"]["type"] == "string"
    assert props["i"]["type"] == "integer"
    assert props["f"]["type"] == "number"
    assert props["b"]["type"] == "boolean"
    assert props["xs"]["type"] == "array"
    assert props["xs"]["items"]["type"] == "string"
    assert props["tags"]["type"] == "object"
    # str | None → anyOf with null
    any_of = props["maybe"].get("anyOf")
    assert any_of is not None
    assert {"type": "null"} in any_of


def test_schema_handles_pydantic_model_parameter() -> None:
    class Filters(BaseModel):
        status: Literal["open", "closed"]
        limit: int = 5

    class Holder:
        @Tool
        def search(self, filters: Filters) -> list[int]:
            """Search using filters."""
            return [filters.limit]

    schema = _get_metadata(Holder.search).json_schema()
    # Pydantic puts the model as a $ref to a defs entry.
    assert "filters" in schema["properties"]
    defs = schema.get("$defs") or schema.get("definitions") or {}
    assert any(name.endswith("Filters") for name in defs)


def test_description_defaults_to_first_docstring_line() -> None:
    class Holder:
        @Tool
        def doc(self, x: int) -> int:
            """First non-empty line.

            Second paragraph that should be dropped.
            """
            return x

    metadata = _get_metadata(Holder.doc)
    assert metadata.description == "First non-empty line."


def test_schema_override_skips_introspection() -> None:
    class Args(BaseModel):
        order_id: str = Field(min_length=4)

    class Holder:
        @Tool(schema=Args)
        def lookup(self, order_id: str) -> str:
            """Override-driven."""
            return order_id

    metadata = _get_metadata(Holder.lookup)
    schema = metadata.json_schema()
    assert schema["properties"]["order_id"]["minLength"] == 4
    assert metadata.schema_model is Args


def test_unannotated_parameter_raises_tool_definition_error() -> None:
    def lookup(self, order_id) -> str:
        return order_id

    with pytest.raises(ToolDefinitionError, match="order_id"):
        Tool(lookup)


def test_var_args_raises_tool_definition_error() -> None:
    def variadic(self, *args: int) -> int:
        return sum(args)

    with pytest.raises(ToolDefinitionError, match="args"):
        Tool(variadic)


def test_schema_override_with_unknown_field_raises() -> None:
    class WrongArgs(BaseModel):
        not_a_param: str

    def lookup(self, order_id: str) -> str:
        """Mismatched override."""
        return order_id

    with pytest.raises(ToolDefinitionError, match="not_a_param"):
        Tool(schema=WrongArgs)(lookup)


# ---------------------------------------------------------------------------
# Discovery by @Agent
# ---------------------------------------------------------------------------


def test_agent_exposes_tools_to_provider_on_complete(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        @Tool
        def echo(self, value: str) -> str:
            """Echo."""
            return value

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert runtime.tool_names == ["echo"]


def test_agent_without_tools_forwards_none(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-opus-4-7", system="…")
    class Demo:
        pass

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert runtime.tool_names == []


def test_external_tools_class_is_discovered(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    class Toolbox:
        @Tool
        def shared(self, x: int) -> int:
            """Shared."""
            return x * 2

    @Agent(model="claude-opus-4-7", system="…", tools=[Toolbox])
    class Demo:
        @Tool
        def local(self, x: int) -> int:
            """Local."""
            return x

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert sorted(runtime.tool_names) == ["local", "shared"]


def test_tool_name_collision_raises_at_decoration(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    class Toolbox:
        @Tool
        def echo(self, x: int) -> int:
            """Dup."""
            return x

    with pytest.raises((AgentConfigError, ToolDefinitionError), match="echo"):

        @Agent(model="claude-opus-4-7", system="…", tools=[Toolbox])
        class _Demo:
            @Tool
            def echo(self, x: int) -> int:
                """Local."""
                return x
