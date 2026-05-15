"""Fly.io deploy target: ``ajolopy deploy fly``.

Generates ``fly.toml`` matching Brief v4.0 §10 + vault doc
``07 - Deploy y Docker`` (section ``## ajolopy deploy fly``) and prints
the five-line ``fly auth login`` → ``fly deploy`` flow the user runs
afterwards.

Pure adapter: the renderer is an f-string concatenation (no TOML
library at runtime, matching the AJ-41 Dockerfile renderer style). The
command driver is the only place that touches the filesystem.
"""

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from .base import DeployContext, DeployResult

if TYPE_CHECKING:
    from collections.abc import Iterable

_FLY_TOML_NAME = "fly.toml"
_PRIMARY_REGION = "iad"


def _render_fly_toml(*, app: str, port: int) -> str:
    """Render the canonical ``fly.toml`` for an Ajolopy project.

    The template is verbatim from Brief v4.0 / doc ``07``. Only the
    application name and the internal port are interpolated; every
    other value is a literal because the Brief pins them.
    """
    return (
        f'app = "{app}"\n'
        f'primary_region = "{_PRIMARY_REGION}"\n'
        "\n"
        "[build]\n"
        '  dockerfile = "Dockerfile"\n'
        "\n"
        "[env]\n"
        '  APP_ENV = "production"\n'
        "\n"
        "[[services]]\n"
        '  protocol = "tcp"\n'
        f"  internal_port = {port}\n"
        "\n"
        "  [[services.ports]]\n"
        "    port = 80\n"
        '    handlers = ["http"]\n'
        "    force_https = true\n"
        "\n"
        "  [[services.ports]]\n"
        "    port = 443\n"
        '    handlers = ["tls", "http"]\n'
        "\n"
        "  [services.concurrency]\n"
        '    type = "connections"\n'
        "    hard_limit = 50\n"
        "    soft_limit = 25\n"
        "\n"
        "[checks]\n"
        "  [checks.health]\n"
        '    type = "http"\n'
        '    interval = "30s"\n'
        '    timeout = "5s"\n'
        '    grace_period = "30s"\n'
        '    method = "get"\n'
        '    path = "/health"\n'
    )


class FlyTarget:
    """Render ``fly.toml`` and print the Fly.io deploy flow."""

    name: ClassVar[str] = "fly"
    description: ClassVar[str] = (
        "Fly.io — generates fly.toml and prints the fly launch / fly deploy flow."
    )

    def prepare(self, ctx: DeployContext) -> DeployResult:
        """Render the ``fly.toml`` contents; the driver writes the file."""
        body = _render_fly_toml(app=ctx.project_name, port=ctx.port)
        return DeployResult(files={Path(_FLY_TOML_NAME): body})

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        """Yield the five commands documented in the Brief, in order.

        The two ``fly secrets set`` lines carry placeholder values
        (``sk-ant-...``, ``postgresql://...``) on purpose: they are
        visible reminders of which secrets the user must set, not
        literal commands to copy-paste.
        """
        # ``ctx`` and ``result`` are accepted for Protocol compatibility
        # with interactive targets; the Fly flow is static.
        del ctx, result
        return (
            "fly auth login",
            "fly secrets set ANTHROPIC_API_KEY=sk-ant-...",
            "fly secrets set DATABASE_URL=postgresql://...",
            "fly launch",
            "fly deploy",
        )


__all__ = ["FlyTarget"]
