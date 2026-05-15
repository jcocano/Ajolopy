"""Shared fixtures + helpers for ``ajolopy generate`` CLI tests.

Every test in the package needs three things:

- A throwaway working directory so ``Path.cwd()`` does not collide
  with the real worktree.
- A fake ``src/<pkg>/`` project layout to exercise auto-detection.
- A way to drive the command end-to-end through the public dispatcher
  so flag handling + registration stay covered.

The helpers stay tiny on purpose — every test file imports them by
name rather than relying on implicit fixture injection so the
dependencies are visible at a glance.
"""

import io
from dataclasses import dataclass
from pathlib import Path

import pytest

from ajolopy.cli.commands import generate as generate_cmd
from ajolopy.cli.dispatcher import build_parser


@dataclass(slots=True, frozen=True)
class CommandResult:
    """Captured result of an ``ajolopy generate`` invocation."""

    exit_code: int
    stdout: str
    stderr: str


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test inside ``tmp_path`` so ``Path.cwd()`` is sandboxed."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_project(root: Path, *, package: str = "myapp") -> Path:
    """Drop a minimal ``src/<package>/`` layout under ``root``.

    Returns the project root for symmetry with the dev-tests helper.
    """
    pkg_dir = root / "src" / package
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture
def fake_project(tmp_cwd: Path) -> Path:
    """Return ``tmp_cwd`` with a single ``src/myapp/`` package inside it."""
    return make_project(tmp_cwd, package="myapp")


def invoke_generate(argv: list[str], *, cwd: Path | None = None) -> CommandResult:
    """Parse and dispatch ``["generate", *argv]`` against the public seam.

    Stdout / stderr are buffered into ``io.StringIO`` and returned
    alongside the exit code so tests can assert against substrings
    without touching the real fds.
    """
    parser = build_parser()
    args = parser.parse_args(["generate", *argv])
    stdout = io.StringIO()
    stderr = io.StringIO()
    target_cwd = cwd if cwd is not None else Path.cwd()
    code = generate_cmd._command(
        args,
        stdout=stdout,
        stderr=stderr,
        cwd=target_cwd,
    )
    return CommandResult(
        exit_code=code,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )
