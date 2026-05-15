"""Renderer behaviour: TTY emoji output vs ``--ci`` JSON."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import doctor as doctor_cmd
from ajolopy.cli.commands.doctor import (
    _DEFAULT_CHECK_NAMES,
    CheckResult,
    _command,
    _render_ci,
    _render_tty,
    _RunReport,
)
from ajolopy.cli.dispatcher import build_parser


def _sample_report() -> _RunReport:
    """Build a small report exercising every status label."""
    results = (
        CheckResult(
            name="python_version",
            passed=True,
            status="ok",
            message="Python 3.14.0",
            duration_ms=0.3,
        ),
        CheckResult(
            name="project_structure",
            passed=False,
            status="fail",
            message="src/<pkg>/main.py not found",
            duration_ms=1.5,
        ),
        CheckResult(
            name="env_file_present",
            passed=None,
            status="warn",
            message=".env not found (using defaults)",
            duration_ms=0.1,
        ),
        CheckResult(
            name="openai_api_key",
            passed=None,
            status="skip",
            message="skipped (not configured)",
            duration_ms=0.0,
        ),
    )
    return _RunReport(results=results, passed=1, failed=1, warnings=1, skipped=1)


class TestRenderTTY:
    def test_emoji_branch_includes_glyphs(self) -> None:
        report = _sample_report()
        stdout = io.StringIO()
        _render_tty(report, stdout=stdout, use_emoji=True)
        text = stdout.getvalue()
        assert "✓" in text
        assert "✗" in text
        # Warning glyph is "⚠️ " — just check the warning sign codepoint.
        assert "⚠" in text
        assert "-" in text
        assert "python_version" in text
        assert "Summary: 1 passed, 1 failed, 1 warnings, 1 skipped" in text
        assert "Exit code: 1" in text

    def test_ascii_branch_uses_bracketed_labels(self) -> None:
        report = _sample_report()
        stdout = io.StringIO()
        _render_tty(report, stdout=stdout, use_emoji=False)
        text = stdout.getvalue()
        assert "[OK]" in text
        assert "[FAIL]" in text
        assert "[WARN]" in text
        assert "[SKIP]" in text
        # No emoji codepoints when ASCII mode is on.
        assert "✓" not in text
        assert "✗" not in text


class TestRenderCI:
    def test_json_matches_spec_schema(self) -> None:
        report = _sample_report()
        stdout = io.StringIO()
        _render_ci(report, stdout=stdout)
        document = json.loads(stdout.getvalue())
        assert document["schema_version"] == 1
        assert document["passed"] == 1
        assert document["failed"] == 1
        assert document["warnings"] == 1
        assert document["skipped"] == 1
        assert document["exit_code"] == 1
        assert isinstance(document["checks"], list)
        first = document["checks"][0]
        assert set(first.keys()) >= {
            "name",
            "passed",
            "message",
            "duration_ms",
        }
        assert first["name"] == "python_version"
        # ``passed`` keeps its tri-state semantics in JSON.
        assert isinstance(document["checks"][2]["passed"], type(None))

    def test_json_has_trailing_newline(self) -> None:
        # Many CI pipelines pipe the doctor's stdout into ``jq``; a trailing
        # newline avoids "incomplete document" warnings.
        report = _sample_report()
        stdout = io.StringIO()
        _render_ci(report, stdout=stdout)
        assert stdout.getvalue().endswith("\n")


# ---------------------------------------------------------------------------
# End-to-end: --ci through the dispatcher
# ---------------------------------------------------------------------------


def _patch_with_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Stub:
        def __init__(self, name: str) -> None:
            self.name = name

        async def run(self) -> tuple[bool | None, str]:
            return True, "ok"

    def _factory(*, cwd: Path) -> list[Any]:
        del cwd
        return [_Stub(name) for name in _DEFAULT_CHECK_NAMES]

    monkeypatch.setattr(doctor_cmd, "_build_checks", _factory)


class TestDispatcherCi:
    def test_ci_flag_emits_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_with_passes(monkeypatch)
        parser = build_parser()
        args = parser.parse_args(["doctor", "--ci"])
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = _command(args, stdout=stdout, stderr=stderr, cwd=tmp_path)
        assert code == doctor_cmd.EXIT_OK
        document = json.loads(stdout.getvalue())
        assert document["passed"] == 12
        assert document["exit_code"] == 0
        # Sanity check: stderr stays clean on a clean run.
        assert stderr.getvalue() == ""


# ---------------------------------------------------------------------------
# Stream introspection: StringIO is treated as a non-TTY.
# ---------------------------------------------------------------------------


class TestIsTty:
    def test_stringio_is_not_tty(self) -> None:
        stream = io.StringIO()
        assert doctor_cmd._is_tty(stream) is False

    def test_stream_without_isatty_falls_back_to_false(self) -> None:
        class _Bare:
            def write(self, _text: str) -> int:
                return 0

        assert doctor_cmd._is_tty(_Bare()) is False  # type: ignore[arg-type]
