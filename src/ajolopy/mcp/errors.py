"""Errors raised by the ``@MCP`` decorator and runtime.

All errors derive from :class:`MCPError` so callers can catch the
framework with a single ``except``. Subclasses signal distinct failure
modes:

- :class:`MCPConfigError` — misconfiguration detected at decoration time
  (empty ``servers=``, unknown scheme, unknown auth key, invalid
  timeout, ``${VAR}`` malformed reference, auth dict provided alongside
  an :class:`MCPClient` instance entry).
- :class:`MCPDependencyError` — the optional ``mcp`` SDK package is not
  installed but the user tried to actually connect to a server. Carries
  the ``pip install ajolopy[mcp]`` hint in the message.
- :class:`MCPToolTimeoutError` — a tool call exceeded the configured
  ``timeout=`` window. Surfaces as a ``tool_result`` with
  ``is_error=True`` so the LLM can adapt.
- :class:`MCPRuntimeError` — generic runtime failure (connect, list
  tools, call tool) that did not match a more specific category.
"""


class MCPError(RuntimeError):
    """Base class for any error raised by the ``@MCP`` primitive."""


class MCPConfigError(MCPError):
    """Misconfiguration detected at decoration time."""


class MCPDependencyError(MCPError):
    """The optional ``mcp`` SDK is not installed.

    Raised the first time the framework tries to actually open a
    connection (factory bootstrap or a direct ``registry.connect_all_for``
    call). The decorator itself is import-clean — users can define
    ``@MCP`` classes in code that ships without the extra installed and
    the import only blows up at connect time.
    """


class MCPToolTimeoutError(MCPError):
    """An MCP tool call exceeded the configured ``timeout=`` window."""


class MCPRuntimeError(MCPError):
    """A runtime MCP operation (connect, list_tools, call_tool) failed."""


__all__ = [
    "MCPConfigError",
    "MCPDependencyError",
    "MCPError",
    "MCPRuntimeError",
    "MCPToolTimeoutError",
]
