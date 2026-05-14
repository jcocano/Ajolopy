"""Decoration-time validation tests for ``@MCP``."""

from typing import override

import pytest

from ajolopy.mcp import MCP, MCPClient, MCPConfigError, ToolSchema


class _DummyCustomClient(MCPClient):
    """Bare-bones MCPClient subclass for the escape-hatch tests."""

    @property
    @override
    def canonical_spec(self) -> str:
        return "fake://dummy"

    @override
    async def connect(self) -> None:  # pragma: no cover - decoration-time use only
        return None

    @override
    async def list_tools(self) -> list[ToolSchema]:  # pragma: no cover
        return []

    @override
    async def call_tool(self, name: str, arguments: object) -> str:  # pragma: no cover
        return "ok"

    @override
    async def aclose(self) -> None:  # pragma: no cover
        return None


def test_stamps_metadata_on_class() -> None:
    @MCP(servers={"github": "stdio:npx -y @mcp/github"})
    class Integrations:
        pass

    meta = Integrations._ajolopy_mcp  # type: ignore[attr-defined]
    assert len(meta.entries) == 1
    entry = meta.entries[0]
    assert entry.key == "github"
    assert entry.spec == "stdio:npx -y @mcp/github"
    assert entry.transport == "stdio"
    assert entry.auth is None


def test_empty_servers_raises() -> None:
    with pytest.raises(MCPConfigError, match="at least one"):

        @MCP(servers=[])
        class _Bad:
            pass


def test_unknown_scheme_raises_with_prefix_list() -> None:
    with pytest.raises(MCPConfigError, match="Accepted prefixes"):

        @MCP(servers={"x": "ftp://example.com/mcp"})
        class _Bad:
            pass


def test_list_form_auto_keys() -> None:
    @MCP(servers=["stdio:a", "https://example.com/mcp"])
    class _M:
        pass

    keys = [e.key for e in _M._ajolopy_mcp.entries]  # type: ignore[attr-defined]
    assert keys == ["server_0", "server_1"]


def test_auth_unknown_key_raises() -> None:
    with pytest.raises(MCPConfigError, match="unknown server key"):

        @MCP(servers={"a": "stdio:cmd"}, auth={"b": {"env": {}}})
        class _Bad:
            pass


def test_auth_with_instance_entry_raises() -> None:
    with pytest.raises(MCPConfigError, match="instance entries"):

        @MCP(
            servers={"x": _DummyCustomClient()},
            auth={"x": {"token": "abc"}},
        )
        class _Bad:
            pass


def test_timeout_zero_raises() -> None:
    with pytest.raises(MCPConfigError):

        @MCP(servers={"x": "stdio:cmd"}, timeout=0)
        class _Bad:
            pass


def test_negative_timeout_raises() -> None:
    with pytest.raises(MCPConfigError):

        @MCP(servers={"x": "stdio:cmd"}, timeout=-1.0)
        class _Bad:
            pass


def test_env_substitution_well_formed_passes() -> None:
    # Decoration-time check only validates the syntax; the variable may
    # not exist yet.
    @MCP(
        servers={"x": "https://example.com/mcp"},
        auth={"x": {"token": "${WELL_FORMED}"}},
    )
    class _M:
        pass

    assert _M._ajolopy_mcp.entries[0].auth == {"token": "${WELL_FORMED}"}  # type: ignore[attr-defined]


def test_env_substitution_malformed_raises() -> None:
    with pytest.raises(MCPConfigError, match="malformed"):

        @MCP(
            servers={"x": "https://example.com/mcp"},
            auth={"x": {"token": "${UNCLOSED"}},
        )
        class _Bad:
            pass


def test_env_substitution_invalid_identifier_raises() -> None:
    with pytest.raises(MCPConfigError, match="valid environment-variable"):

        @MCP(
            servers={"x": "https://example.com/mcp"},
            auth={"x": {"token": "${0starts_with_digit}"}},
        )
        class _Bad:
            pass


def test_class_type_is_preserved() -> None:
    @MCP(servers={"x": "stdio:cmd"})
    class Same:
        marker = "kept"

    assert Same.marker == "kept"


def test_custom_client_entry_transport_is_custom() -> None:
    instance = _DummyCustomClient()

    @MCP(servers={"x": instance})
    class _M:
        pass

    entry = _M._ajolopy_mcp.entries[0]  # type: ignore[attr-defined]
    assert entry.transport == "custom"
    assert entry.spec is instance
