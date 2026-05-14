"""Metadata defaults derived at decoration time."""

import pytest

from ajolopy import MCPServer, Tool
from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR
from ajolopy.mcp_server.metadata import kebab_case_class_name, strip_docstring


class TestKebabCaseName:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("MyTools", "my-tools"),
            ("MyToolsBundle", "my-tools-bundle"),
            ("Foo", "foo"),
            ("X", "x"),
            ("ABTest", "a-b-test"),
        ],
    )
    def test_kebab_case(self, source: str, expected: str) -> None:
        assert kebab_case_class_name(source) == expected


class TestStripDocstring:
    def test_none_returns_none(self) -> None:
        assert strip_docstring(None) is None

    def test_empty_returns_none(self) -> None:
        assert strip_docstring("   \n\t  ") is None

    def test_strips_and_preserves_lines(self) -> None:
        doc = "\n  First line.\n  Second line.\n"
        assert strip_docstring(doc) == "First line.\n  Second line."


class TestDefaultsFromDecoration:
    def test_name_defaults_to_kebab_class_name(self) -> None:
        @MCPServer(transport="stdio")
        class MyToolsBundle:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(MyToolsBundle, MCP_SERVER_META_ATTR)
        assert meta.name == "my-tools-bundle"

    def test_name_override_wins(self) -> None:
        @MCPServer(transport="stdio", name="custom-name")
        class MyTools:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(MyTools, MCP_SERVER_META_ATTR)
        assert meta.name == "custom-name"

    def test_version_default(self) -> None:
        @MCPServer(transport="stdio")
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.version == "0.0.0"

    def test_version_override(self) -> None:
        @MCPServer(transport="stdio", version="1.2.3")
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.version == "1.2.3"

    def test_instructions_default_from_docstring(self) -> None:
        @MCPServer(transport="stdio")
        class T:
            """Order management helpers."""

            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.instructions == "Order management helpers."

    def test_instructions_default_empty_docstring_becomes_none(self) -> None:
        @MCPServer(transport="stdio")
        class T:
            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.instructions is None

    def test_instructions_override(self) -> None:
        @MCPServer(transport="stdio", instructions="Override.")
        class T:
            """Doc."""

            @Tool
            def x(self) -> str:
                return "ok"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert meta.instructions == "Override."

    def test_bindings_are_frozen_tuple(self) -> None:
        @MCPServer(transport="stdio")
        class T:
            @Tool
            def a(self) -> str:
                return "a"

            @Tool
            def b(self) -> str:
                return "b"

        meta = getattr(T, MCP_SERVER_META_ATTR)
        assert isinstance(meta.bindings, tuple)
        names = {b.metadata.name for b in meta.bindings}
        assert names == {"a", "b"}
