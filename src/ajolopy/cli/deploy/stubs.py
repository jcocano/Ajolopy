"""Placeholder targets for the cloud platforms still pending v0.1.

Each stub registers under its public name so ``ajolopy deploy --help``
lists every v0.1 target from day one. The stubs emit no files and
print a single line pointing at the board item that ships the real
implementation:

- :class:`VercelStub` → ``AJ-45``

The Fly.io adapter shipped with ``AJ-42`` (see
:mod:`ajolopy.cli.deploy.fly`), the Railway adapter with ``AJ-43``
(:mod:`ajolopy.cli.deploy.railway`), and the Render adapter with
``AJ-44`` (:mod:`ajolopy.cli.deploy.render`). None of them has a stub
representation here any longer.

When an owning item lands its real adapter, the new module calls
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


class VercelStub(_Stub):
    name: ClassVar[str] = "vercel"
    description: ClassVar[str] = "Vercel — manifest generation (ships in AJ-45)."
    _board_item: ClassVar[str] = "AJ-45"
    _platform_label: ClassVar[str] = "Vercel"


__all__ = ["VercelStub"]
