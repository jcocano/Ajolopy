"""Transport adapters for ``@MCPServer``.

Each module wraps a single ``mcp.server.*`` transport so the rest of
the framework speaks the same shape regardless of which one the user
picked. The SDK imports stay local to each module's function bodies,
preserving the "import-clean without ``ajolopy[mcp]``" guarantee
documented in :mod:`ajolopy.mcp_server`.
"""

from .http import build_streamable_http_endpoint
from .sse import build_sse_get_endpoint, build_sse_post_endpoint
from .stdio import run_stdio

__all__ = [
    "build_sse_get_endpoint",
    "build_sse_post_endpoint",
    "build_streamable_http_endpoint",
    "run_stdio",
]
