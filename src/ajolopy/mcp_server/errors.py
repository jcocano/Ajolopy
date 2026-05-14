"""Errors raised by the ``@MCPServer`` decorator and runtime.

All errors derive from :class:`MCPServerError` so callers can catch the
publish-side surface with a single ``except``. Subclasses signal distinct
failure modes:

- :class:`MCPServerConfigError` -- misconfiguration detected at decoration
  time (unknown transport, missing or malformed ``path=``, ``@UseGuards``
  combined with ``transport="stdio"``, host class with no ``@Tool``
  methods, required-arg ``__init__`` at mount time, duplicate routes,
  non-callable ``server_factory``).
- :class:`MCPServerRuntimeError` -- something went wrong while booting or
  serving (the lowlevel server raised, the stdio loop crashed). Tool
  exceptions DO NOT surface here; they round-trip as
  ``CallToolResult(isError=True, ...)`` per the MCP protocol.

:class:`MCPDependencyError` is intentionally re-exported from
:mod:`ajolopy.mcp.errors` so both the consume side (AJ-7) and the
publish side (AJ-60) share the same "install ``ajolopy[mcp]``" exception
class. The two packages otherwise stay decoupled.
"""

from ajolopy.mcp.errors import MCPDependencyError


class MCPServerError(RuntimeError):
    """Base class for any error raised by the ``@MCPServer`` primitive."""


class MCPServerConfigError(MCPServerError):
    """Misconfiguration detected at decoration time or mount time."""


class MCPServerRuntimeError(MCPServerError):
    """A runtime operation (boot, serve, transport handoff) failed."""


__all__ = [
    "MCPDependencyError",
    "MCPServerConfigError",
    "MCPServerError",
    "MCPServerRuntimeError",
]
