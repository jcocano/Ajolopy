"""``@MCP`` primitive — declarative connection-and-tool-discovery surface.

Importing this package is import-clean: it does not require the optional
``ajolopy[mcp]`` extra. Decorating classes also works without the SDK
installed — only the *runtime* path (actually connecting to a server)
needs the ``mcp`` package on ``sys.path``.
"""

from .client import (
    HTTPMCPClient,
    MCPClient,
    SSEMCPClient,
    StdioMCPClient,
    ToolSchema,
)
from .decorator import MCP, MCPMetadata
from .errors import (
    MCPConfigError,
    MCPDependencyError,
    MCPError,
    MCPRuntimeError,
    MCPToolTimeoutError,
)
from .registry import (
    MCPRegistry,
    ServerEntry,
    get_mcp_registry,
    reset_mcp_registry,
)

__all__ = [
    "MCP",
    "HTTPMCPClient",
    "MCPClient",
    "MCPConfigError",
    "MCPDependencyError",
    "MCPError",
    "MCPMetadata",
    "MCPRegistry",
    "MCPRuntimeError",
    "MCPToolTimeoutError",
    "SSEMCPClient",
    "ServerEntry",
    "StdioMCPClient",
    "ToolSchema",
    "get_mcp_registry",
    "reset_mcp_registry",
]
