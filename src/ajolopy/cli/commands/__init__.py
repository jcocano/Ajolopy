"""Subcommand registry for the ``ajolopy`` CLI.

:func:`register_subcommands` is the seam future CLI items (AJ-32 ff)
will extend. Each subcommand module exposes a ``register(sub)``
function that attaches its parser to the shared
``argparse._SubParsersAction``; calling it from here keeps the
dispatcher unaware of any particular subcommand's implementation.
"""

from typing import TYPE_CHECKING

from . import eval as eval_cmd
from . import mcp_serve

if TYPE_CHECKING:
    import argparse


def register_subcommands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach every known subcommand to the dispatcher's ``sub`` action.

    ``argparse._SubParsersAction`` is the documented seam for typed
    subparser registration in the stdlib but has no public alias. The
    ``pyright`` ignore is intentional and shared with the matching
    annotation in :mod:`ajolopy.cli.commands.mcp_serve`.
    """
    mcp_serve.register(sub)
    eval_cmd.register(sub)


__all__ = ["register_subcommands"]
