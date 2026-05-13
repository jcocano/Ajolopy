"""Pure-Python renderers for the canonical deploy artifacts.

The three renderers return ``str`` and have no I/O side effects. The
``ajolopy new`` / ``ajolopy build`` / ``ajolopy deploy`` CLI commands
own the "where to write the bytes" decision.
"""

from .compose import DatabaseChoice, render_docker_compose
from .dockerfile import render_dockerfile
from .dockerignore import render_dockerignore

__all__ = [
    "DatabaseChoice",
    "render_docker_compose",
    "render_dockerfile",
    "render_dockerignore",
]
