"""Acceptance: ``run()`` convenience wrapper.

``run()`` is a thin asyncio + signal-handler wrapper. The acceptance
test launches it in a subprocess so the signal handling can be
exercised without affecting the parent test process.
"""

import os
import signal
import subprocess
import sys
import time


def _run_in_subprocess(module_source: str, *, port: int) -> subprocess.Popen[bytes]:
    """Launch ``run(AppModule, port=...)`` in a fresh subprocess."""
    script = (
        "from ajolopy import Module, run\n"
        f"{module_source}\n"
        f'run(AppModule, port={port}, host="127.0.0.1")\n'
    )
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(  # noqa: S603 — script is framework-controlled, never user input
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def test_run_starts_and_handles_sigint() -> None:
    """``run`` launches the server and exits cleanly on SIGINT."""
    module_source = "@Module()\nclass AppModule: ...\n"
    proc = _run_in_subprocess(module_source, port=0)
    try:
        # Give the server time to bind + start serving. AJ-80 bumped this
        # from 1.0s to 3.0s: eager-registering all four built-in providers
        # at ``import ajolopy`` time made package import slower (the Gemini
        # SDK's ``from google import genai`` alone takes ~1-2s on CI), so
        # a 1s window let SIGINT race the import phase and the process
        # died with -2 instead of the clean 0 from uvicorn's handler.
        time.sleep(3.0)
        # Server should still be running.
        assert proc.poll() is None, (
            f"Server exited prematurely: code={proc.returncode}, "
            f"stderr={proc.stderr.read().decode() if proc.stderr else ''}"
        )

        # SIGINT should trigger a clean shutdown.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise

        # uvicorn's clean-exit code is 0; the framework's run() should match.
        assert proc.returncode == 0, (
            f"Expected clean exit (0), got {proc.returncode}; "
            f"stderr={proc.stderr.read().decode() if proc.stderr else ''}"
        )
    finally:
        if proc.poll() is None:
            proc.kill()


def test_run_with_faulty_module_exits_nonzero() -> None:
    """A duplicate-provider AppModule fails fast with non-zero exit."""
    module_source = (
        "@Module(providers=[int])\n"
        "class A: ...\n"
        "@Module(imports=[A], providers=[int])\n"
        "class AppModule: ...\n"
    )
    proc = _run_in_subprocess(module_source, port=0)
    try:
        proc.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise

    assert proc.returncode != 0, "Expected non-zero exit for invalid module"
    stderr = (proc.stderr.read().decode() if proc.stderr else "").lower()
    assert "duplicate" in stderr or "factorystartuperror" in stderr
