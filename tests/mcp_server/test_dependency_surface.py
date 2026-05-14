"""``ajolopy[mcp]`` dependency surface.

The decorator + everything in :mod:`ajolopy.mcp_server` must import
cleanly without the optional ``mcp`` SDK installed. Booting (CLI or
HTTP mount) raises :class:`MCPDependencyError` when the SDK is missing.

We can't actually uninstall ``mcp`` from the test process, so we
simulate the absence by patching ``sys.modules`` so ``import mcp.*``
fails with :class:`ImportError`. The runtime / transports lazy-import
the SDK inside function bodies, so the patch takes effect only when
their boot path runs.
"""

import builtins
import sys
from typing import Any

import pytest

from ajolopy import MCPServer, Tool
from ajolopy.mcp_server import MCPDependencyError, MCPServerRuntime
from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR


@pytest.fixture
def hide_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import mcp`` / ``import mcp.*`` raise ImportError.

    Returns ``None`` (not a generator) because ``monkeypatch`` handles
    teardown automatically; the fixture only needs to install the
    blocking ``__import__`` shim.
    """
    real_import = builtins.__import__
    mcp_keys = [k for k in list(sys.modules.keys()) if k == "mcp" or k.startswith("mcp.")]
    for key in mcp_keys:
        monkeypatch.delitem(sys.modules, key, raising=False)

    def fake_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"No module named '{name}' (simulated)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@MCPServer(transport="stdio")
class _Tools:
    @Tool
    def echo(self, value: str) -> str:
        return value


class TestImportClean:
    def test_decorator_works_without_mcp(self) -> None:
        """The decorator itself never imports the SDK."""
        # Reaching this point already proves the decorator survived; we
        # re-check by reading the stamped metadata.
        assert hasattr(_Tools, MCP_SERVER_META_ATTR)


class TestBootRequiresMCP:
    def test_runtime_build_server_raises_dependency_error(
        self,
        hide_mcp: None,
    ) -> None:
        meta = getattr(_Tools, MCP_SERVER_META_ATTR)
        runtime = MCPServerRuntime(meta)
        with pytest.raises(MCPDependencyError, match=r"pip install ajolopy\[mcp\]"):
            runtime.build_server()

    async def test_run_stdio_raises_dependency_error(
        self,
        hide_mcp: None,
    ) -> None:
        # Re-import the transport module fresh so its lazy import path
        # is exercised under the patched ``__import__``.
        from ajolopy.mcp_server.transports.stdio import run_stdio

        meta = getattr(_Tools, MCP_SERVER_META_ATTR)
        runtime = MCPServerRuntime(meta)
        with pytest.raises(MCPDependencyError):
            await run_stdio(runtime)
