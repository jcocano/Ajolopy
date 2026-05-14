"""Argparse-based dispatcher for the ``ajolopy`` console script.

Mirrors :func:`tools.board.main`: a single ``build_parser`` registers
every subcommand and ``main(argv)`` parses + calls the bound handler.
Each subcommand handler is a function returning an exit code (``int``);
``main`` propagates the code as ``SystemExit`` so the console script
exits cleanly.

The dispatcher itself owns no MCP / framework knowledge -- every
subcommand registers its parser via :func:`register_subcommands`. Future
items (AJ-32 ff) add their commands by extending the registry without
touching this module's body.
"""

import argparse
from typing import TYPE_CHECKING

from .commands import register_subcommands

if TYPE_CHECKING:
    from collections.abc import Callable


def build_parser() -> argparse.ArgumentParser:
    """Build the root ``ajolopy`` parser with every registered subcommand."""
    parser = argparse.ArgumentParser(
        prog="ajolopy",
        description="Ajolopy command-line interface.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="subcommand")
    register_subcommands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` (defaults to ``sys.argv``) and dispatch.

    Returns the subcommand's exit code so callers (tests, embedding
    processes) can assert against it. The installed console script
    raises ``SystemExit(code)`` so OS exit codes match.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


__all__ = ["build_parser", "main"]
