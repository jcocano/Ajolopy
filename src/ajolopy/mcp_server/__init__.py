"""``@MCPServer`` primitive -- publish ``@Tool`` methods over MCP.

Companion to :mod:`ajolopy.mcp` (the AJ-7 consume side). The two
packages share the optional ``ajolopy[mcp]`` extra and the
:class:`MCPDependencyError` error class but have no import-time
dependency on each other: ``ajolopy.mcp`` consumes external MCP
servers, ``ajolopy.mcp_server`` publishes the local class's ``@Tool``
methods to MCP clients (Claude Desktop, other agent frameworks, etc).

Importing this package is import-clean -- it does not require the
optional ``ajolopy[mcp]`` extra. Decorating classes also works
without the SDK installed; only the runtime path (the CLI's
``mcp-serve`` subcommand or ``create_app(mcp_servers=[...])``)
needs the ``mcp`` package on ``sys.path``.
"""

from .decorator import MCPServer
from .errors import (
    MCPDependencyError,
    MCPServerConfigError,
    MCPServerError,
    MCPServerRuntimeError,
)
from .metadata import MCPServerMetadata, ServerFactory, Transport
from .mount import mount_mcp_servers
from .runtime import MCPServerRuntime

__all__ = [
    "MCPDependencyError",
    "MCPServer",
    "MCPServerConfigError",
    "MCPServerError",
    "MCPServerMetadata",
    "MCPServerRuntime",
    "MCPServerRuntimeError",
    "ServerFactory",
    "Transport",
    "mount_mcp_servers",
]
