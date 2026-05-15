"""Railway deploy target: ``ajolopy deploy railway``.

Renders a single ``railway.json`` manifest that Railway's build
pipeline consumes: ``DOCKERFILE`` builder against the production
target, plus the deploy block with the ``uvicorn`` start command and
the standard ``/health`` health check. The shape is verbatim from
Brief v4.0 §10 / vault doc ``07 - Deploy y Docker``.

The target is **pure**: ``prepare`` returns the manifest bytes, the
command driver writes them to disk and prints the next steps. v0.1
deliberately does not invoke the ``railway`` CLI — the next-step
strings are printed for the user to run themselves.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from .base import DeployContext, DeployResult

if TYPE_CHECKING:
    from collections.abc import Iterable

_MANIFEST_NAME = "railway.json"
_SCHEMA_URL = "https://railway.app/railway.schema.json"
_HEALTHCHECK_PATH = "/health"
_HEALTHCHECK_TIMEOUT = 30
_RESTART_POLICY = "ON_FAILURE"
_RESTART_MAX_RETRIES = 3


class RailwayTarget:
    """Render the ``railway.json`` manifest for Railway's build + deploy pipeline."""

    name: ClassVar[str] = "railway"
    description: ClassVar[str] = (
        "Railway — generate railway.json (DOCKERFILE builder + uvicorn start + /health check)."
    )

    def prepare(self, ctx: DeployContext) -> DeployResult:
        """Render ``railway.json`` from the Brief's verbatim template."""
        manifest: dict[str, object] = {
            "$schema": _SCHEMA_URL,
            "build": {
                "builder": "DOCKERFILE",
                "dockerfilePath": "Dockerfile",
                "buildTarget": "production",
            },
            "deploy": {
                "startCommand": (f"uvicorn {ctx.app_module} --host 0.0.0.0 --port $PORT"),
                "healthcheckPath": _HEALTHCHECK_PATH,
                "healthcheckTimeout": _HEALTHCHECK_TIMEOUT,
                "restartPolicyType": _RESTART_POLICY,
                "restartPolicyMaxRetries": _RESTART_MAX_RETRIES,
            },
        }
        # ``sort_keys=False`` preserves insertion order so the rendered
        # file matches the Brief's example top-to-bottom.
        contents = json.dumps(manifest, indent=2, sort_keys=False) + "\n"
        return DeployResult(files={Path(_MANIFEST_NAME): contents})

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        """Print the three Railway CLI commands the user runs themselves."""
        # ``ctx`` / ``result`` are kept on the signature for forward
        # compatibility with the Protocol; the Railway flow is purely
        # static (no project-name interpolation).
        del ctx, result
        return (
            "railway login",
            "railway link",
            "railway up",
        )


__all__ = ["RailwayTarget"]
