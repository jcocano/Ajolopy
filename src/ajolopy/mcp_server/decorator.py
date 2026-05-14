"""``@MCPServer`` class decorator.

Validates the configuration at decoration time, discovers every
``@Tool``-decorated method on the host class, and stamps the class
with an :class:`MCPServerMetadata` record under the
``_ajolopy_mcp_server`` attribute. The decorator never imports the
``mcp`` SDK or starts a server -- booting is the consumer's job
(``ajolopy mcp-serve`` for stdio, ``create_app(mcp_servers=[Cls])``
for HTTP / SSE).

The composition story with :func:`ajolopy.guards.UseGuards` is
intentionally constrained: HTTP / SSE pick up the guard chain at mount
time through :func:`apply_guard_chain`, but ``transport="stdio"``
rejects ``@UseGuards`` because the parent process is the trust
boundary -- there is no per-request envelope to gate.
"""

import inspect
import re
from typing import TYPE_CHECKING, Any, TypeVar

from ajolopy.agent.tool import discover_tools
from ajolopy.guards.decorator import GUARDS_META_ATTR

if TYPE_CHECKING:
    from collections.abc import Callable

from .errors import MCPServerConfigError
from .metadata import (
    MCPServerMetadata,
    ServerFactory,
    Transport,
    kebab_case_class_name,
    strip_docstring,
)

# Module-level TypeVar (manual rather than PEP 695) so the substantial
# pre-decoration validation in ``MCPServer`` does not trip CodeQL's
# "potentially uninitialised local variable" false positive that fires
# when a PEP 695 type parameter is used in a function with branches
# that may raise before the inner ``_decorate`` is reached. The classic
# TypeVar form is semantically identical and silences the false positive
# without changing the public typing.
T = TypeVar("T")

# Public attribute name the runtime + mount + CLI all read.
MCP_SERVER_META_ATTR = "_ajolopy_mcp_server"

_ACCEPTED_TRANSPORTS: tuple[Transport, ...] = ("stdio", "http", "sse")
_PATH_RE = re.compile(r"^/[a-zA-Z0-9_\-/]*$")
_STDIO_GUARDS_HINT = (
    '@UseGuards is not supported on transport="stdio" -- the parent '
    'process is the trust boundary. Use transport="http" / "sse" if '
    "you need request-level auth."
)


def MCPServer(  # noqa: N802 -- public surface mirrors the Brief's primitive name.
    *,
    transport: Transport,
    path: str | None = None,
    name: str | None = None,
    version: str = "0.0.0",
    instructions: str | None = None,
    server_factory: ServerFactory | None = None,
) -> Callable[[type[T]], type[T]]:
    """Mark a class as an MCP server publishing its ``@Tool`` methods.

    See ``specs/mcp-server.md`` for the full surface and acceptance
    criteria. The decorator validates the transport, path, version, and
    factory at decoration time; tool discovery happens once on the
    decorated class so the wire tool list is frozen.
    """
    _validate_transport(transport)
    _validate_path(transport, path)
    _validate_version(version)
    _validate_instructions(instructions)
    _validate_name(name)
    _validate_server_factory(server_factory)

    def _decorate(cls: type[T]) -> type[T]:
        _validate_host_class(cls)
        _validate_no_stdio_guards(cls, transport)
        bindings, _extra_instances = discover_tools(cls, None)
        if not bindings:
            raise MCPServerConfigError(
                f"@MCPServer({cls.__qualname__}) host class declares no "
                f"@Tool methods. Add at least one @Tool-decorated method "
                f"before publishing the class as an MCP server."
            )
        resolved_name = name if name is not None else kebab_case_class_name(cls.__name__)
        resolved_instructions = (
            instructions if instructions is not None else strip_docstring(cls.__doc__)
        )
        metadata = MCPServerMetadata(
            transport=transport,
            path=path,
            name=resolved_name,
            version=version,
            instructions=resolved_instructions,
            bindings=tuple(bindings),
            server_factory=server_factory,
            original_cls=cls,
        )
        # Stamp the metadata last so ``@UseGuards`` decorators that wrap
        # ``@MCPServer`` (either ordering) can be detected at mount /
        # runtime time even if the user wrote them above the class.
        setattr(cls, MCP_SERVER_META_ATTR, metadata)
        return cls

    return _decorate


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_transport(transport: object) -> None:
    if transport not in _ACCEPTED_TRANSPORTS:
        raise MCPServerConfigError(
            f"@MCPServer transport={transport!r} is not supported. "
            f"Accepted values: {list(_ACCEPTED_TRANSPORTS)!r}."
        )


def _validate_path(transport: Transport, path: object) -> None:
    if transport == "stdio":
        if path is not None:
            raise MCPServerConfigError(
                '@MCPServer(transport="stdio") does not accept path= -- '
                "stdio communicates over process pipes, not URLs."
            )
        return
    if path is None:
        raise MCPServerConfigError(
            f'@MCPServer(transport={transport!r}) requires a path= kwarg (e.g. path="/mcp").'
        )
    if not isinstance(path, str) or not path:
        raise MCPServerConfigError(f"@MCPServer path= must be a non-empty string, got {path!r}.")
    if not _PATH_RE.fullmatch(path):
        raise MCPServerConfigError(
            f"@MCPServer path={path!r} must start with '/' and contain only "
            f"alphanumerics, '_', '-', or '/'."
        )


def _validate_version(version: object) -> None:
    if not isinstance(version, str) or not version:
        raise MCPServerConfigError(
            f"@MCPServer version= must be a non-empty string, got {version!r}."
        )


def _validate_instructions(instructions: object) -> None:
    if instructions is None:
        return
    if not isinstance(instructions, str):
        raise MCPServerConfigError(
            f"@MCPServer instructions= must be a string or None, got {type(instructions).__name__}."
        )


def _validate_name(name: object) -> None:
    if name is None:
        return
    if not isinstance(name, str) or not name:
        raise MCPServerConfigError(
            f"@MCPServer name= must be a non-empty string or None, got {name!r}."
        )


def _validate_server_factory(server_factory: object) -> None:
    if server_factory is None:
        return
    if not callable(server_factory):
        raise MCPServerConfigError(
            f"@MCPServer server_factory= must be callable, got {type(server_factory).__name__}."
        )


def _validate_host_class(cls: object) -> None:
    """Reject decoration targets that are not user-defined classes."""
    # Defensive: ``@MCPServer`` is documented to decorate a class; users
    # accidentally pasting the decorator on a function would otherwise
    # surface the failure deeper inside discover_tools. The isinstance
    # check is intentional even though the typed surface narrows ``cls``
    # to ``type[T]`` in the decorator's inner closure.
    if not isinstance(cls, type):
        raise MCPServerConfigError(
            f"@MCPServer must decorate a class, got {type(cls).__name__}: {cls!r}."
        )
    try:
        sig = inspect.signature(cls)
    except TypeError, ValueError:
        # Builtins or C-extension classes -- treat as opaque, let the
        # instantiation fail later if needed.
        return
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.default is inspect.Parameter.empty and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise MCPServerConfigError(
                f"@MCPServer host class {cls.__qualname__} requires "
                f"constructor argument {name!r}. Either give it a default "
                f"value or pass a pre-built instance to "
                f"create_app(mcp_servers=[{cls.__name__}(...)])."
            )


def _validate_no_stdio_guards(cls: type[Any], transport: Transport) -> None:
    if transport != "stdio":
        return
    if cls.__dict__.get(GUARDS_META_ATTR) is not None:
        raise MCPServerConfigError(_STDIO_GUARDS_HINT)


__all__ = [
    "MCP_SERVER_META_ATTR",
    "MCPServer",
]
