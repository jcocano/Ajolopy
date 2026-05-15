"""Placeholder targets for the cloud platforms still pending v0.1.

Each stub registers under its public name so ``ajolopy deploy --help``
lists every v0.1 target from day one. The stubs emit no files and
print a single line pointing at the board item that ships the real
implementation:

- :class:`FlyStub` → ``AJ-42`` (Fly.io)
- :class:`RenderStub` → ``AJ-44``
- :class:`VercelStub` → ``AJ-45``

Railway's real implementation already landed (``AJ-43``) and lives in
:mod:`ajolopy.cli.deploy.railway`.

When the owning item lands its real adapter, the new module calls
``register_target(<RealTarget>())`` at import time and the registry's
last-write-wins semantics promote it without touching this file.
"""

from typing import TYPE_CHECKING, ClassVar

from .base import DeployContext, DeployResult

if TYPE_CHECKING:
    from collections.abc import Iterable


class _Stub:
    """Common stub behaviour: no files, one note + one next-step line."""

    name: ClassVar[str]
    description: ClassVar[str]
    _board_item: ClassVar[str]
    _platform_label: ClassVar[str]

    def prepare(self, ctx: DeployContext) -> DeployResult:
        del ctx
        note = (
            f"{self._platform_label} deploy target lands via "
            f"{self._board_item}. See board.json for status."
        )
        return DeployResult(files={}, notes=(note,))

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        del ctx, result
        return (
            f"Tracking item: {self._board_item}. "
            f"For now, follow the {self._platform_label} docs manually.",
        )


class FlyStub(_Stub):
    name: ClassVar[str] = "fly"
    description: ClassVar[str] = "Fly.io — manifest generation (ships in AJ-42)."
    _board_item: ClassVar[str] = "AJ-42"
    _platform_label: ClassVar[str] = "Fly.io"


class RenderStub(_Stub):
    name: ClassVar[str] = "render"
    description: ClassVar[str] = "Render — manifest generation (ships in AJ-44)."
    _board_item: ClassVar[str] = "AJ-44"
    _platform_label: ClassVar[str] = "Render"


class VercelStub(_Stub):
    name: ClassVar[str] = "vercel"
    description: ClassVar[str] = "Vercel — manifest generation (ships in AJ-45)."
    _board_item: ClassVar[str] = "AJ-45"
    _platform_label: ClassVar[str] = "Vercel"


__all__ = ["FlyStub", "RenderStub", "VercelStub"]
