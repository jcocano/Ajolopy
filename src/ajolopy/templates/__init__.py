"""Code-generation templates shipped with the framework.

Each submodule is a small, parametric renderer that returns ``str`` and
performs no I/O. Callers (CLI commands such as ``ajolopy new``,
``ajolopy build``, and the per-target deploy items) decide where to
write the bytes. This keeps the templates testable without filesystem
fixtures and stops the same multi-stage layout from drifting across
unrelated CLI subcommands.
"""

from .docker import (
    DatabaseChoice,
    render_docker_compose,
    render_dockerfile,
    render_dockerignore,
)

__all__ = [
    "DatabaseChoice",
    "render_docker_compose",
    "render_dockerfile",
    "render_dockerignore",
]
