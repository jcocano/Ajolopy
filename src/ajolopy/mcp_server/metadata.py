"""Decoration-time metadata stamped on every ``@MCPServer``-marked class.

The metadata is read at three later points: the CLI's ``mcp-serve``
subcommand (to gate stdio targets and pull the server name), the mount
layer (to register Starlette routes), and the runtime (to drive
``list_tools`` / ``call_tool`` dispatch). Holding it as an immutable
dataclass keeps the public seam small and stable.

The :func:`kebab_case_class_name` helper implements the documented
default for the ``name=`` kwarg: ``MyToolsBundle`` becomes
``"my-tools-bundle"``. ``strip_docstring`` mirrors the docstring
extraction the agent layer already uses for ``@Tool`` descriptions.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from ajolopy.agent.tool import ToolBinding


Transport = Literal["stdio", "http", "sse"]
"""The three transports the publish side ships in v0.1."""


ServerFactory = Any
"""User escape hatch: ``(MCPServerMetadata, list[ToolBinding]) -> mcp.server.lowlevel.Server``.

Typed as :data:`typing.Any` because the return value is an instance of
the optional ``mcp`` SDK's ``Server`` class. Holding a real type here
would force every importer of :mod:`ajolopy.mcp_server` to pull the
SDK; the spec mandates that the decorator stay import-clean. The
factory's runtime shape is validated by the runtime layer instead.
"""


@dataclass(frozen=True, slots=True)
class MCPServerMetadata:
    """Configuration captured at decoration time on a ``@MCPServer`` class.

    Stamped on the class as ``_ajolopy_mcp_server``. The dataclass is
    frozen so the runtime cannot mutate the configuration the user
    declared; new state (the cached single instance, the lowlevel
    ``Server``) lives on the :class:`MCPServerRuntime` instead.
    """

    transport: Transport
    path: str | None
    name: str
    version: str
    instructions: str | None
    bindings: tuple[ToolBinding, ...]
    server_factory: Callable[..., Any] | None = None
    original_cls: type[Any] = field(default=type(None))  # set by the decorator


_PASCAL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def kebab_case_class_name(class_name: str) -> str:
    """Convert ``PascalCase`` / ``camelCase`` to ``kebab-case``.

    Examples:
        >>> kebab_case_class_name("MyToolsBundle")
        'my-tools-bundle'
        >>> kebab_case_class_name("FooBar")
        'foo-bar'
        >>> kebab_case_class_name("X")
        'x'
    """
    if not class_name:
        return class_name
    # Insert a hyphen before every uppercase letter that follows a
    # non-leading character; then lowercase everything.
    return _PASCAL_BOUNDARY.sub("-", class_name).lower()


def strip_docstring(doc: str | None) -> str | None:
    """Normalise a class docstring for the MCP ``instructions`` field.

    Empty / whitespace-only docstrings collapse to :data:`None` so the
    framework forwards ``instructions=None`` to the SDK rather than an
    empty string.
    """
    if doc is None:
        return None
    stripped = doc.strip()
    if not stripped:
        return None
    # Collapse the common ``"""<newline>body<newline>"""`` indentation pattern.
    lines = [line.rstrip() for line in stripped.splitlines()]
    return "\n".join(lines).strip() or None


__all__ = [
    "MCPServerMetadata",
    "ServerFactory",
    "Transport",
    "kebab_case_class_name",
    "strip_docstring",
]
