"""Reusable fakes for the AJ-60 @MCPServer test suite.

Two seams:

- :class:`FakeMCPLowLevelServer` -- a stand-in for the SDK's
  ``mcp.server.lowlevel.Server`` used by the runtime + transport tests
  that want to assert against the registered ``list_tools`` /
  ``call_tool`` handlers without speaking JSON-RPC.
- :func:`make_eof_stdio_pipe` -- builds an :func:`anyio` text pipe that
  yields immediate EOF, letting the CLI smoke test drive the real
  ``mcp.server.stdio.stdio_server`` context manager to a clean shutdown
  without spawning a subprocess.
"""

import io
from typing import Any


class FakeMCPLowLevelServer:
    """Captures the handlers registered against an ``mcp`` lowlevel ``Server``.

    The class implements just enough of the SDK shape for
    :meth:`ajolopy.mcp_server.runtime.MCPServerRuntime.build_server` to
    return successfully when patched in via a ``server_factory``. The
    runtime registers a ``list_tools()`` handler and a ``call_tool()``
    handler; the fake records both so dispatch tests can invoke them
    directly.
    """

    def __init__(self, name: str = "fake-server", version: str = "0.0.0") -> None:
        self.name = name
        self.version = version
        self.list_tools_handler: Any = None
        self.call_tool_handler: Any = None
        self.run_called_with: Any = None

    def list_tools(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.list_tools_handler = fn
            return fn

        return decorator

    def call_tool(self, *, validate_input: bool = True) -> Any:
        def decorator(fn: Any) -> Any:
            self.call_tool_handler = fn
            return fn

        return decorator

    def create_initialization_options(self) -> Any:
        return None

    async def run(
        self,
        read_stream: Any,
        write_stream: Any,
        initialization_options: Any,
    ) -> None:
        self.run_called_with = (read_stream, write_stream, initialization_options)


def make_eof_stdin() -> io.BytesIO:
    """Return an empty in-memory ``BytesIO`` suitable for the stdio loop.

    An immediate EOF makes ``mcp.server.stdio.stdio_server``'s reader
    task exit cleanly, which in turn closes its memory object stream
    and unblocks ``Server.run`` so the CLI returns 0.
    """
    return io.BytesIO()


__all__ = [
    "FakeMCPLowLevelServer",
    "make_eof_stdin",
]
