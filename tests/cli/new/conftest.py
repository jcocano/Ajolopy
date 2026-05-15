"""Shared fixtures for the ``ajolopy new`` CLI tests.

Every test in this package needs the cwd pointed at a temporary
directory (otherwise ``Path.cwd() / project_name`` collides with the
real working tree) and a way to drive the command end-to-end. The
helpers here live in one place so each test file can stay focused on
its specific acceptance case.
"""

import argparse
import io
from dataclasses import dataclass
from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from ajolopy.cli.dispatcher import build_parser


@dataclass(slots=True, frozen=True)
class CommandResult:
    """Captured result of an ``ajolopy new`` invocation."""

    exit_code: int
    stdout: str
    stderr: str


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test inside ``tmp_path`` so ``Path.cwd()`` is sandboxed."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def invoke_new(argv: list[str]) -> CommandResult:
    """Parse and dispatch ``argv`` via the public dispatcher seam.

    Mirrors the production code path so flag handling and registration
    are exercised together. Stdout / stderr are captured into in-memory
    buffers and returned alongside the exit code.
    """
    parser = build_parser()
    args = parser.parse_args(["new", *argv])
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = new_cmd._command(args, stdout=stdout, stderr=stderr)
    return CommandResult(exit_code=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


def make_namespace(**overrides: object) -> argparse.Namespace:
    """Return an :class:`argparse.Namespace` with sane defaults for the new cmd."""
    defaults: dict[str, object] = {
        "project_name": "demo",
        "yes": True,
        "llm": None,
        "feature": None,
        "no_docker": False,
        "no_eval": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
