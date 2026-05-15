"""Reference deploy target: ``ajolopy deploy docker``.

Generates the universal ``Dockerfile.prod`` and ``.dockerignore`` that
cover k8s / VPS / ECS / on-prem / any-container-runner. Both files are
rendered by :mod:`ajolopy.templates.docker` (AJ-41); this target is a
thin adapter that maps :class:`DeployContext` onto the renderer's
kwargs and returns the bytes for the command driver to write.
"""

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from ajolopy.templates.docker import render_dockerfile, render_dockerignore

from .base import DeployContext, DeployResult

if TYPE_CHECKING:
    from collections.abc import Iterable

_DOCKERFILE_NAME = "Dockerfile.prod"
_DOCKERIGNORE_NAME = ".dockerignore"


class DockerTarget:
    """Render the production Dockerfile + dockerignore for any container runtime."""

    name: ClassVar[str] = "docker"
    description: ClassVar[str] = (
        "Universal Dockerfile.prod + .dockerignore for k8s / VPS / ECS / on-prem."
    )

    def prepare(self, ctx: DeployContext) -> DeployResult:
        """Render both files; the command driver decides where to write them."""
        dockerfile = render_dockerfile(
            python_version=ctx.python_version,
            app_module=ctx.app_module,
            port=ctx.port,
        )
        dockerignore = render_dockerignore()
        return DeployResult(
            files={
                Path(_DOCKERFILE_NAME): dockerfile,
                Path(_DOCKERIGNORE_NAME): dockerignore,
            },
        )

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        """Print the build + run commands the user runs themselves."""
        # ``next_steps`` is documented as taking ``result`` for forward
        # compatibility with stubs / interactive targets; the docker
        # target does not need it today.
        del result
        image = f"{ctx.project_name}:latest"
        return (
            f"docker build -f {_DOCKERFILE_NAME} -t {image} .",
            f"docker run -p {ctx.port}:{ctx.port} --env-file .env {image}",
        )


__all__ = ["DockerTarget"]
