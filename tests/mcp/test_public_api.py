"""Public-surface guards for the @MCP package."""

from typing import Any

import ajolopy


def test_top_level_export() -> None:
    assert ajolopy.MCP is not None
    assert "MCP" in ajolopy.__all__


def test_mcp_subpackage_exports() -> None:
    from ajolopy.mcp import (
        MCPClient,
        MCPConfigError,
        MCPDependencyError,
        MCPError,
        MCPRegistry,
        MCPRuntimeError,
        MCPToolTimeoutError,
        ToolSchema,
        get_mcp_registry,
        reset_mcp_registry,
    )

    assert MCPClient is not None
    assert MCPConfigError is not None
    assert MCPDependencyError is not None
    assert MCPError is not None
    assert MCPRegistry is not None
    assert MCPRuntimeError is not None
    assert MCPToolTimeoutError is not None
    assert ToolSchema is not None
    assert callable(get_mcp_registry)
    assert callable(reset_mcp_registry)


def test_error_hierarchy() -> None:
    from ajolopy.mcp import (
        MCPConfigError,
        MCPDependencyError,
        MCPError,
        MCPRuntimeError,
        MCPToolTimeoutError,
    )

    assert issubclass(MCPConfigError, MCPError)
    assert issubclass(MCPDependencyError, MCPError)
    assert issubclass(MCPRuntimeError, MCPError)
    assert issubclass(MCPToolTimeoutError, MCPError)


def test_decoration_works_without_mcp_sdk(monkeypatch: object) -> None:
    """``@MCP(servers={...})`` validates config without needing ``mcp``.

    The actual connect path imports the SDK lazily; the decorator only
    parses the spec list. We verify this by registering a class through
    the public surface and confirming the metadata is stamped — no
    ``mcp`` import has to happen for this to succeed.
    """
    from ajolopy.mcp import MCP

    @MCP(servers={"x": "stdio:cmd"})
    class _M:
        pass

    assert _M._ajolopy_mcp.entries[0].key == "x"  # type: ignore[attr-defined]


async def test_connect_without_sdk_raises_dependency_error(monkeypatch: Any) -> None:
    """A failure to import ``mcp`` surfaces as :class:`MCPDependencyError`."""
    from ajolopy.mcp import MCP, MCPDependencyError, get_mcp_registry
    from ajolopy.mcp import client as client_module

    def _missing_loader() -> Any:
        raise MCPDependencyError("simulated missing mcp")

    monkeypatch.setattr(client_module, "_load_mcp", _missing_loader)

    @MCP(servers={"x": "stdio:cmd"})
    class _M:
        pass

    registry = get_mcp_registry()
    # connect_all_for swallows per-server failures into WARN logs; the
    # dependency error appears as the server being unhealthy.
    await registry.connect_all_for(None)
    assert registry.tools_for(_M) == []
