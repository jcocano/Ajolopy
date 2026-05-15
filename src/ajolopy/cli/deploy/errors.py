"""Error types raised by the ``ajolopy deploy`` machinery.

Every error here carries a user-actionable message; the command driver
prints :attr:`Exception.args[0]` verbatim and maps the class to a stable
exit code (see :mod:`ajolopy.cli.commands.deploy`).
"""


class DeployTargetError(Exception):
    """Base error for the deploy CLI surface.

    Targets that hit an unexpected internal failure (template rendering
    blew up, an absolute path slipped through, ...) raise this directly.
    The command driver maps it to :data:`EXIT_INTERNAL`.
    """


class DeployTargetNotFoundError(DeployTargetError):
    """Raised when the user asked for a target that is not registered."""


class DeployFilesExistError(DeployTargetError):
    """Raised when one or more output files already exist and ``--force`` was not set."""


class DeployUserAbortError(DeployTargetError):
    """Raised when an interactive target prompts the user and they decline.

    AJ-45's Vercel warning gate is the canonical caller; the command
    driver converts this into :data:`EXIT_USER_ABORT` without a
    traceback so the CLI looks intentional.
    """


__all__ = [
    "DeployFilesExistError",
    "DeployTargetError",
    "DeployTargetNotFoundError",
    "DeployUserAbortError",
]
