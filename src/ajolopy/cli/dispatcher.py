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

Argparse subparser names cannot contain ``:``. The user-facing
``env:show`` / ``env:validate`` / ``env:diff`` subcommands therefore use
``env-show`` / ``env-validate`` / ``env-diff`` as the internal parser
names; :func:`_rewrite_colon_aliases` rewrites the first ``argv``
element before argparse sees it so both forms invoke the same handler.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ajolopy import __version__

from ._dotenv import load_dotenv
from .commands import register_subcommands

if TYPE_CHECKING:
    from collections.abc import Callable


# Mapping from user-facing colon form to the argparse-friendly hyphen
# form. Kept tiny on purpose: only commands that include a ``:`` in
# their public name need an entry. Tests assert against this mapping
# directly so a typo here cannot regress silently.
COLON_ALIASES: dict[str, str] = {
    "env:show": "env-show",
    "env:validate": "env-validate",
    "env:diff": "env-diff",
}


def _rewrite_colon_aliases(argv: list[str]) -> list[str]:
    """Return ``argv`` with the first colon-form subcommand rewritten.

    Only ``argv[0]`` (the subcommand slot) is considered; any later
    occurrence is treated as a value the user typed deliberately (for
    example a ``--filter`` pattern) and is left untouched.
    """
    if not argv:
        return argv
    head = argv[0]
    replacement = COLON_ALIASES.get(head)
    if replacement is None:
        return argv
    return [replacement, *argv[1:]]


def build_parser() -> argparse.ArgumentParser:
    """Build the root ``ajolopy`` parser with every registered subcommand."""
    parser = argparse.ArgumentParser(
        prog="ajolopy",
        description="Ajolopy command-line interface.",
    )
    # ``--version`` is a top-level argparse action so ``ajolopy --version``
    # prints the package version and exits cleanly without requiring a
    # subcommand (regression: AJ-83).
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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
    effective: list[str] = list(sys.argv[1:]) if argv is None else list(argv)
    effective = _rewrite_colon_aliases(effective)
    parser = build_parser()
    args = parser.parse_args(effective)
    # AJ-93 — load ``cwd/.env`` BEFORE the subcommand handler runs so
    # every CLI subcommand that imports user code (``dev``, ``eval``,
    # ``doctor``, ``env:*``, ``generate``) sees the same env vars a
    # production server would. Idempotent — safe even if a specific
    # subcommand also calls ``load_dotenv`` internally.
    load_dotenv(cwd=Path.cwd(), environ=os.environ)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


__all__ = ["COLON_ALIASES", "build_parser", "main"]
