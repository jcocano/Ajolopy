"""Tests for :class:`ajolopy.cli.deploy.vercel.VercelTarget`.

The Vercel target is the only v0.1 deploy target that prompts the
user inside :meth:`DeployTarget.prepare`. Tests inject ``stdin`` and
``stdout`` via the constructor so the gate runs hermetically and we
can assert on the exact warning text without touching real streams.
"""

import io
import json
from pathlib import Path

import pytest

from ajolopy.cli.deploy import DeployContext
from ajolopy.cli.deploy.errors import DeployUserAbortError
from ajolopy.cli.deploy.vercel import VercelTarget


def _ctx(project_root: Path, *, yes: bool = False) -> DeployContext:
    """Build a deploy context with sensible defaults for these tests."""
    return DeployContext(
        project_root=project_root,
        app_module="main:app",
        port=3000,
        python_version="3.14",
        project_name="acme",
        is_tty=False,
        yes=yes,
        dry_run=False,
        force=False,
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_name_is_vercel() -> None:
    assert VercelTarget().name == "vercel"


def test_description_mentions_vercel() -> None:
    assert "Vercel" in VercelTarget().description


# ---------------------------------------------------------------------------
# ``ctx.yes=True`` skips the gate
# ---------------------------------------------------------------------------


def test_yes_flag_skips_prompt_and_returns_one_file(tmp_path: Path) -> None:
    stdout = io.StringIO()
    # ``stdin`` is intentionally empty: if the gate ran, the readline()
    # call would return ``""`` and the target would abort. ``yes=True``
    # short-circuits the prompt, so we expect a clean DeployResult.
    target = VercelTarget(stdin=io.StringIO(""), stdout=stdout)
    result = target.prepare(_ctx(tmp_path, yes=True))
    assert set(result.files) == {Path("vercel.json")}
    # And nothing was printed — the gate was bypassed entirely.
    assert stdout.getvalue() == ""


def test_yes_flag_emits_canonical_vercel_json(tmp_path: Path) -> None:
    target = VercelTarget(stdin=io.StringIO(""), stdout=io.StringIO())
    result = target.prepare(_ctx(tmp_path, yes=True))
    contents = result.files[Path("vercel.json")]
    payload = json.loads(contents)
    assert payload["version"] == 2
    assert payload["builds"] == [{"src": "main.py", "use": "@vercel/python"}]
    assert payload["routes"] == [{"src": "/(.*)", "dest": "main.py"}]
    # Trailing newline keeps the file POSIX-friendly and matches the
    # convention used by ``render_dockerfile`` / ``render_dockerignore``.
    assert contents.endswith("\n")


# ---------------------------------------------------------------------------
# Interactive gate — affirmative answers proceed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["y\n", "Y\n", "yes\n", "YES\n", "  yes  \n"])
def test_affirmative_answer_proceeds(tmp_path: Path, answer: str) -> None:
    target = VercelTarget(stdin=io.StringIO(answer), stdout=io.StringIO())
    result = target.prepare(_ctx(tmp_path))
    assert Path("vercel.json") in result.files


# ---------------------------------------------------------------------------
# Interactive gate — declines abort with DeployUserAbortError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["n\n", "N\n", "no\n", "\n", "garbage\n"])
def test_decline_raises_user_abort(tmp_path: Path, answer: str) -> None:
    target = VercelTarget(stdin=io.StringIO(answer), stdout=io.StringIO())
    with pytest.raises(DeployUserAbortError) as excinfo:
        target.prepare(_ctx(tmp_path))
    assert "vercel" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Warning text content
# ---------------------------------------------------------------------------


def test_warning_text_covers_documented_sections(tmp_path: Path) -> None:
    stdout = io.StringIO()
    target = VercelTarget(stdin=io.StringIO("y\n"), stdout=stdout)
    target.prepare(_ctx(tmp_path))
    printed = stdout.getvalue()
    # The four documented sections from Brief v4.0 §10.
    assert "Vercel for Python AI apps has serious limitations" in printed
    assert "If your app has" in printed
    assert "Vercel works well for" in printed
    assert "Continue with Vercel? (y/N)" in printed


def test_warning_text_lists_concrete_limits(tmp_path: Path) -> None:
    stdout = io.StringIO()
    target = VercelTarget(stdin=io.StringIO("y\n"), stdout=stdout)
    target.prepare(_ctx(tmp_path))
    printed = stdout.getvalue()
    # Spot-check each bullet so a future edit to the warning text
    # cannot silently drop one of the limitations.
    assert "300s" in printed
    assert "Cold starts" in printed
    assert "Fly.io or Railway" in printed
    assert "Single-turn short agents" in printed


# ---------------------------------------------------------------------------
# Next steps
# ---------------------------------------------------------------------------


def test_next_steps_yields_three_vercel_commands(tmp_path: Path) -> None:
    target = VercelTarget(stdin=io.StringIO(""), stdout=io.StringIO())
    ctx = _ctx(tmp_path, yes=True)
    steps = list(target.next_steps(ctx, target.prepare(ctx)))
    assert len(steps) == 3
    assert steps[0].startswith("vercel login")
    assert steps[1].startswith("vercel link")
    assert steps[2].startswith("vercel deploy --prod")


# ---------------------------------------------------------------------------
# Production defaults — constructor with no arguments must not blow up
# ---------------------------------------------------------------------------


def test_default_constructor_does_not_touch_streams_until_prepare() -> None:
    # The registry calls VercelTarget() with no arguments at import time;
    # that must succeed without reading sys.stdin (which would block in
    # pytest). The lazy stream binding inside ``_run_warning_gate`` is
    # what enables this — guarding the contract explicitly here.
    target = VercelTarget()
    assert target.name == "vercel"
