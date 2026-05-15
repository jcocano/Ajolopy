"""Public surface of the ``ajolopy deploy`` package.

Importing this module registers every v0.1 target in declaration order:

1. :class:`~ajolopy.cli.deploy.docker.DockerTarget` — AJ-37 (reference).
2. :class:`~ajolopy.cli.deploy.fly.FlyTarget` — AJ-42.
3. :class:`~ajolopy.cli.deploy.railway.RailwayTarget` — AJ-43.
4. :class:`~ajolopy.cli.deploy.render.RenderTarget` — AJ-44.
5. :class:`~ajolopy.cli.deploy.vercel.VercelTarget` — AJ-45 (with
   interactive warning gate; pass ``-y`` to skip).

All v0.1 cloud targets are now real implementations — no stubs remain.
"""

from .base import DeployContext, DeployResult, DeployTarget
from .docker import DockerTarget
from .errors import (
    DeployFilesExistError,
    DeployTargetError,
    DeployTargetNotFoundError,
    DeployUserAbortError,
)
from .fly import FlyTarget
from .railway import RailwayTarget
from .registry import get_target, list_targets, register_target
from .render import RenderTarget
from .vercel import VercelTarget

# Register defaults in display order. Re-importing this module is a
# no-op for the registry because ``register_target`` overrides the
# slot in place (idempotent).
register_target(DockerTarget())
register_target(FlyTarget())
register_target(RailwayTarget())
register_target(RenderTarget())
register_target(VercelTarget())

__all__ = [
    "DeployContext",
    "DeployFilesExistError",
    "DeployResult",
    "DeployTarget",
    "DeployTargetError",
    "DeployTargetNotFoundError",
    "DeployUserAbortError",
    "DockerTarget",
    "FlyTarget",
    "RailwayTarget",
    "RenderTarget",
    "VercelTarget",
    "get_target",
    "list_targets",
    "register_target",
]
