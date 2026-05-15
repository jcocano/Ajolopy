"""Public Protocol + value types for the ``ajolopy deploy`` surface.

The deploy command treats each target as a black box that maps a
:class:`DeployContext` to a :class:`DeployResult`. The Protocol is
intentionally narrow so AJ-42 / AJ-43 / AJ-44 / AJ-45 can each ship
their target as a tiny module with no inheritance.

Targets are pure: ``prepare`` returns the bytes that *should* be
written; the command driver is the only place that touches the
filesystem. Targets that need an interactive prompt before any file
is rendered raise :class:`ajolopy.cli.deploy.errors.DeployUserAbort`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class DeployContext:
    """Inputs threaded into every target.

    Built once by the command driver. Targets MUST NOT mutate it (the
    dataclass is frozen — re-derive a new context if a step needs a
    different value).
    """

    project_root: Path
    app_module: str
    port: int
    python_version: str
    project_name: str
    is_tty: bool
    yes: bool
    dry_run: bool
    force: bool


@dataclass(slots=True, frozen=True)
class DeployResult:
    """Files + notes a target's :meth:`DeployTarget.prepare` returns.

    ``files`` keys are relative to :attr:`DeployContext.project_root`.
    Absolute paths or paths containing ``..`` raise
    :class:`ajolopy.cli.deploy.errors.DeployTargetError` at write time.
    """

    files: dict[Path, str]
    notes: tuple[str, ...] = ()


@runtime_checkable
class DeployTarget(Protocol):
    """The shape every deploy target implements.

    Targets register themselves with :func:`ajolopy.cli.deploy.registry.register_target`
    at import time. The dispatcher imports :mod:`ajolopy.cli.deploy`
    once, so by the time ``ajolopy deploy --help`` runs every target
    is in the registry.
    """

    name: ClassVar[str]
    description: ClassVar[str]

    def prepare(self, ctx: DeployContext) -> DeployResult: ...
    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]: ...


__all__ = ["DeployContext", "DeployResult", "DeployTarget"]
