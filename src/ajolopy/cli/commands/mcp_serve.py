"""``ajolopy mcp-serve <module>:<class>`` subcommand.

The handler:

1. Parses ``<module>:<class>`` (exactly one ``:`` separator; whitespace
   stripped from each half). Malformed targets exit with
   :data:`EXIT_USAGE`.
2. Imports the module via :func:`importlib.import_module`. Import
   failures exit with :data:`EXIT_IMPORT_ERROR`.
3. ``getattr`` the class. Missing attribute exits with
   :data:`EXIT_TARGET_NOT_FOUND`.
4. Verifies the target carries ``_ajolopy_mcp_server`` metadata AND
   that the transport is ``"stdio"``; otherwise exits with
   :data:`EXIT_NOT_STDIO_SERVER` pointing at ``transport="stdio"``.
5. Builds an :class:`MCPServerRuntime`, materialises the host instance,
   and runs the stdio transport via
   :func:`ajolopy.mcp_server.transports.run_stdio`.

The CLI does NOT import the ``mcp`` SDK eagerly -- the transport
module pulls it in lazily so the dispatcher (and the rest of the
``ajolopy`` console script's surface) stays import-clean.
"""

import argparse  # noqa: TC003 -- argparse.Namespace is used at runtime by argparse itself
import asyncio
import importlib

from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR
from ajolopy.mcp_server.metadata import MCPServerMetadata
from ajolopy.mcp_server.runtime import MCPServerRuntime
from ajolopy.mcp_server.transports.stdio import run_stdio

# Module-level exit-code constants -- shared with the CLI tests so a
# rename in one place updates both. Mirrors the convention used by GNU
# coreutils (``EX_USAGE = 64``) but trimmed to the spec's documented
# codes.
EXIT_OK = 0
EXIT_IMPORT_ERROR = 1
EXIT_TARGET_NOT_FOUND = 1
EXIT_NOT_STDIO_SERVER = 1
EXIT_USAGE = 2


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``mcp-serve`` subparser to the dispatcher.

    ``_SubParsersAction`` is the documented type for argparse's
    subparser registry; the pyright ignore mirrors
    :func:`ajolopy.cli.commands.register_subcommands`.
    """
    parser = sub.add_parser(
        "mcp-serve",
        help='Run an @MCPServer(transport="stdio") class as a stdio MCP server.',
        description=(
            "Import the target class, verify it is decorated with "
            '@MCPServer(transport="stdio"), instantiate it, and run the '
            "stdio MCP loop until EOF on stdin."
        ),
    )
    parser.add_argument(
        "target",
        help="Module path and class name in the form 'package.module:ClassName'.",
    )
    parser.set_defaults(func=cmd_mcp_serve)


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Resolve the target, validate, and drive the stdio loop."""
    target: str = args.target
    module_name, class_name, err = _parse_target(target)
    if err is not None:
        print(err)
        return EXIT_USAGE

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"ajolopy mcp-serve: module not found: {module_name}: {exc}")
        return EXIT_IMPORT_ERROR
    except Exception as exc:  # pragma: no cover - defensive
        print(f"ajolopy mcp-serve: import error on {module_name}: {exc}")
        return EXIT_IMPORT_ERROR

    cls = getattr(module, class_name, None)
    if cls is None:
        print(f"ajolopy mcp-serve: attribute not found: '{class_name}' on module '{module_name}'.")
        return EXIT_TARGET_NOT_FOUND

    metadata = getattr(cls, MCP_SERVER_META_ATTR, None)
    if not isinstance(metadata, MCPServerMetadata):
        print(
            f"ajolopy mcp-serve: {module_name}:{class_name} is not "
            f"decorated with @MCPServer. Apply "
            f'@MCPServer(transport="stdio") to the class first.'
        )
        return EXIT_NOT_STDIO_SERVER
    if metadata.transport != "stdio":
        print(
            f"ajolopy mcp-serve: {module_name}:{class_name} declares "
            f"transport={metadata.transport!r}; only "
            f'transport="stdio" is supported for the CLI. Mount HTTP '
            f"/ SSE servers via create_app(mcp_servers=[...]) instead."
        )
        return EXIT_NOT_STDIO_SERVER

    runtime = MCPServerRuntime(metadata)
    asyncio.run(run_stdio(runtime))
    return EXIT_OK


def _parse_target(target: str) -> tuple[str, str, str | None]:
    """Return ``(module, class, error_message_or_None)`` for a CLI target."""
    if not isinstance(target, str) or not target.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
        return ("", "", "ajolopy mcp-serve: empty target.")
    parts = target.split(":")
    if len(parts) != 2:
        return (
            "",
            "",
            (
                f"ajolopy mcp-serve: target {target!r} is not in the "
                f"expected 'package.module:ClassName' format."
            ),
        )
    module_name = parts[0].strip()
    class_name = parts[1].strip()
    if not module_name or not class_name:
        return (
            "",
            "",
            (
                f"ajolopy mcp-serve: target {target!r} is missing either "
                f"the module or the class name. Expected "
                f"'package.module:ClassName'."
            ),
        )
    return (module_name, class_name, None)


__all__ = [
    "EXIT_IMPORT_ERROR",
    "EXIT_NOT_STDIO_SERVER",
    "EXIT_OK",
    "EXIT_TARGET_NOT_FOUND",
    "EXIT_USAGE",
    "cmd_mcp_serve",
    "register",
]
