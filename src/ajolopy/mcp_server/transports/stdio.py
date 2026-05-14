"""``stdio`` transport for ``@MCPServer``.

Wraps :func:`mcp.server.stdio.stdio_server` so the CLI's ``mcp-serve``
subcommand can drive the publish-side server with a single ``await``
call. The ``mcp`` SDK import lives inside the function body so that
``from ajolopy.mcp_server import MCPServer`` works without the
optional ``ajolopy[mcp]`` extra installed.
"""

from typing import TYPE_CHECKING

from ajolopy.mcp_server.errors import MCPDependencyError

if TYPE_CHECKING:
    from ajolopy.mcp_server.runtime import MCPServerRuntime


async def run_stdio(runtime: MCPServerRuntime) -> None:
    """Serve ``runtime`` over the stdio transport until EOF on stdin.

    Returns once :func:`mcp.server.stdio.stdio_server`'s context manager
    exits cleanly (EOF on stdin or the parent process closes the pipe).
    Raises :class:`MCPDependencyError` if the optional ``mcp`` SDK is
    not installed; any other exception bubbles out to the CLI which
    translates it to ``EXIT_IMPORT_ERROR``.
    """
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover - exercised in dependency test
        raise MCPDependencyError(
            "The 'mcp' SDK is required to run an @MCPServer over stdio. "
            "Install it with 'pip install ajolopy[mcp]'."
        ) from exc

    runtime.emit_boot_span()
    server = runtime.build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


__all__ = ["run_stdio"]
