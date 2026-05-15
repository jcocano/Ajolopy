"""Deploy target: ``ajolopy deploy render``.

Generates the ``render.yaml`` Blueprint that Render's dashboard
consumes verbatim. The YAML body is built with a pure f-string +
concatenation so the output is deterministic for snapshot-style
tests; PyYAML is only used by tests to parse and assert against the
result.

Render uses git-based deploys and their CLI is read-only, so the
target's ``next_steps`` instruct the user to commit/push the file and
visit the Render Blueprints dashboard.
"""

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from .base import DeployContext, DeployResult

if TYPE_CHECKING:
    from collections.abc import Iterable

_RENDER_YAML_NAME = "render.yaml"

# Module-level constants so tests can assert by identity / equality
# without re-typing the strings.
_NEXT_STEP_PUSH = "Commit and push the generated render.yaml to your repo."
_NEXT_STEP_DASHBOARD = "Visit https://dashboard.render.com/blueprints to apply the blueprint."


def _render_yaml(*, project_name: str, port: int) -> str:
    """Render the ``render.yaml`` body for a single Docker-based web service.

    The output matches Brief v4.0 §10 / vault doc ``07 - Deploy y Docker``,
    section ``ajolopy deploy render`` — do not add fields without first
    updating that document and ``specs/render-deploy.md``.
    """
    return (
        "services:\n"
        "  - type: web\n"
        f"    name: {project_name}\n"
        "    runtime: docker\n"
        "    dockerfilePath: ./Dockerfile\n"
        "    dockerTarget: production\n"
        "    plan: starter\n"
        "    healthCheckPath: /health\n"
        "    envVars:\n"
        "      - key: APP_ENV\n"
        "        value: production\n"
        "      - key: PORT\n"
        f"        value: {port}\n"
    )


class RenderTarget:
    """Render Blueprint generator — emits ``render.yaml`` for the dashboard flow."""

    name: ClassVar[str] = "render"
    description: ClassVar[str] = (
        "Render — render.yaml Blueprint for the Docker-based web service flow."
    )

    def prepare(self, ctx: DeployContext) -> DeployResult:
        """Render ``render.yaml``; the command driver decides where to write it."""
        body = _render_yaml(project_name=ctx.project_name, port=ctx.port)
        return DeployResult(files={Path(_RENDER_YAML_NAME): body})

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        """Tell the user to push the file and apply it in the Render dashboard."""
        # Render's CLI is read-only — the deploy is initiated from the
        # dashboard once the Blueprint file is committed.
        del ctx, result
        return (_NEXT_STEP_PUSH, _NEXT_STEP_DASHBOARD)


__all__ = ["RenderTarget"]
