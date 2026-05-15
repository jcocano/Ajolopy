"""Public surface of the ``ajolopy deploy`` package.

Importing this module registers every v0.1 target in declaration order:

1. :class:`~ajolopy.cli.deploy.docker.DockerTarget` — the reference
   implementation that ships with AJ-37.
2. :class:`~ajolopy.cli.deploy.fly.FlyTarget` — the Fly.io adapter
   that ships with AJ-42.
3. :class:`~ajolopy.cli.deploy.railway.RailwayTarget` — AJ-43.
4. :class:`~ajolopy.cli.deploy.stubs.RenderStub` — AJ-44.
5. :class:`~ajolopy.cli.deploy.stubs.VercelStub` — AJ-45.

The follow-up items re-register their real target after importing
their own module; the registry's last-write-wins semantics promote
them without touching this file.
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
from .stubs import RenderStub, VercelStub

# Register defaults in display order. Re-importing this module is a
# no-op for the registry because ``register_target`` overrides the
# slot in place (idempotent).
register_target(DockerTarget())
register_target(FlyTarget())
register_target(RailwayTarget())
register_target(RenderStub())
register_target(VercelStub())

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
    "RenderStub",
    "VercelStub",
    "get_target",
    "list_targets",
    "register_target",
]
