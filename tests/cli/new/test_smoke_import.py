"""Smoke import: the generated package imports cleanly in a subprocess.

The subprocess is required because the generated package depends on
``ajolopy`` being importable AND on ``sys.path`` carrying the generated
``src/`` tree. We borrow the parent venv's site-packages (where
``ajolopy`` is installed in dev mode) so the test runs without an extra
``uv sync`` step.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new

_SENTINEL = "SMOKE_IMPORT_OK"
_CHAT_SENTINEL = "CHAT_ROUTE_MOUNTED"


def _import_command(package_name: str) -> str:
    """Return the Python one-liner the subprocess runs.

    Importing the provider package binds ``LLMProvider`` to the
    ``anthropic`` routing key so the agent decorator can resolve
    ``claude-opus-4-7`` without raising ``ProviderNotRegisteredError``.
    ``ANTHROPIC_API_KEY`` is set in the subprocess env so provider
    instantiation does not require a real key either. After the import
    we walk the Starlette router and assert ``/chat`` is mounted (AJ-95
    regression — workflow + mcp scaffolds previously omitted ``@Stream``
    so ``ajolopy dev`` started but ``curl /chat`` returned 404).
    """
    return (
        f"import ajolopy.providers.anthropic; "
        f"from {package_name} import main as _m; "
        f"paths = [getattr(r, 'path', None) for r in _m.app.router.routes]; "
        f"assert '/chat' in paths, f'expected /chat route, got: {{paths!r}}'; "
        f"print({_CHAT_SENTINEL!r}); "
        f"print({_SENTINEL!r})"
    )


@pytest.mark.parametrize("feature", ["agent", "workflow", "mcp"])
def test_generated_package_imports_cleanly(
    tmp_cwd: Path,
    feature: str,
) -> None:
    """``import {package_name}.main`` succeeds for every feature variant."""
    result = invoke_new(
        [
            "my-agent",
            "--yes",
            "--feature",
            feature,
            "--no-docker",
            "--no-eval",
        ]
    )
    assert result.exit_code == new_cmd.EXIT_OK, result.stderr

    project = tmp_cwd / "my-agent"
    src_dir = project / "src"

    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = "test-dummy"
    env["OPENAI_API_KEY"] = "test-dummy"
    env["GOOGLE_API_KEY"] = "test-dummy"
    # Prepend the generated ``src/`` so the subprocess can import it.
    env["PYTHONPATH"] = os.pathsep.join([str(src_dir), env.get("PYTHONPATH", "")]).strip(os.pathsep)

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _import_command("my_agent")],
        env=env,
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
    assert _SENTINEL in completed.stdout
