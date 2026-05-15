"""Runner orchestration: exit codes, ``--skip``, error containment.

Drives :func:`_run_checks` and the :func:`_command` entry point with a
mix of real checks (for the deterministic pass/fail) and stub checks
(for the exit-code and warning-vs-fail branches the spec demands).
"""

import asyncio
import io
import time
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import doctor as doctor_cmd
from ajolopy.cli.commands.doctor import (
    _DEFAULT_CHECK_NAMES,
    CheckResult,
    _build_checks,
    _command,
    _run_checks,
    _RunReport,
)
from ajolopy.cli.dispatcher import build_parser

# ---------------------------------------------------------------------------
# Stub check helpers
# ---------------------------------------------------------------------------


class _StubCheck:
    """A check whose ``run()`` returns a pre-recorded outcome."""

    def __init__(
        self,
        *,
        name: str,
        outcome: tuple[bool | None, str],
        sleep_s: float = 0.0,
        raises: BaseException | None = None,
    ) -> None:
        self.name = name
        self._outcome = outcome
        self._sleep_s = sleep_s
        self._raises = raises

    async def run(self) -> tuple[bool | None, str]:
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        if self._raises is not None:
            raise self._raises
        return self._outcome


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestRunChecksAggregation:
    async def test_all_pass_exits_zero(self) -> None:
        checks = [
            _StubCheck(name="a", outcome=(True, "ok")),
            _StubCheck(name="b", outcome=(True, "ok")),
        ]
        report = await _run_checks(checks, skip=frozenset())
        assert report.passed == 2
        assert report.failed == 0
        assert report.exit_code == doctor_cmd.EXIT_OK

    async def test_single_fail_exits_one(self) -> None:
        checks = [
            _StubCheck(name="a", outcome=(True, "ok")),
            _StubCheck(name="b", outcome=(False, "broken")),
        ]
        report = await _run_checks(checks, skip=frozenset())
        assert report.failed == 1
        assert report.exit_code == doctor_cmd.EXIT_FAIL

    async def test_warning_does_not_flip_exit_code(self) -> None:
        checks = [
            _StubCheck(name="a", outcome=(True, "ok")),
            _StubCheck(name="b", outcome=(None, "warning message")),
        ]
        report = await _run_checks(checks, skip=frozenset())
        assert report.warnings == 1
        assert report.failed == 0
        assert report.exit_code == doctor_cmd.EXIT_OK

    async def test_skip_message_counts_as_skipped(self) -> None:
        checks = [
            _StubCheck(name="a", outcome=(None, "skipped (not configured)")),
        ]
        report = await _run_checks(checks, skip=frozenset())
        assert report.skipped == 1
        assert report.warnings == 0

    async def test_exception_inside_check_marks_as_fail(self) -> None:
        checks = [
            _StubCheck(name="a", outcome=(True, "ok"), raises=RuntimeError("boom")),
        ]
        report = await _run_checks(checks, skip=frozenset())
        assert report.failed == 1
        result = report.results[0]
        assert result.status == "fail"
        assert "RuntimeError" in result.message
        assert "boom" in result.message

    async def test_skip_via_set_records_skipped_result(self) -> None:
        checks = [
            _StubCheck(name="python_version", outcome=(False, "should not run")),
            _StubCheck(name="b", outcome=(True, "ok")),
        ]
        report = await _run_checks(checks, skip=frozenset({"python_version"}))
        # Skipped name appears in the result list with status="skip" and a
        # message acknowledging the --skip flag.
        first = report.results[0]
        assert first.name == "python_version"
        assert first.status == "skip"
        assert "--skip" in first.message
        assert report.skipped == 1
        assert report.passed == 1
        assert report.failed == 0


class TestDuration:
    async def test_duration_is_recorded(self) -> None:
        checks = [
            _StubCheck(name="a", outcome=(True, "ok"), sleep_s=0.01),
        ]
        started = time.perf_counter()
        report = await _run_checks(checks, skip=frozenset())
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        # The check itself slept ~10ms; the recorded duration should be
        # in the same ballpark and bounded above by the wallclock elapsed.
        assert report.results[0].duration_ms >= 8.0
        assert report.results[0].duration_ms <= elapsed_ms + 5.0


# ---------------------------------------------------------------------------
# _build_checks — the 12 default checks line up with the spec's list.
# ---------------------------------------------------------------------------


class TestBuildChecks:
    def test_returns_twelve_checks_in_spec_order(self, tmp_path: Path) -> None:
        checks = _build_checks(cwd=tmp_path)
        names = [c.name for c in checks]
        assert names == list(_DEFAULT_CHECK_NAMES)
        assert len(checks) == 12


# ---------------------------------------------------------------------------
# _command — full dispatch entry, no network.
# ---------------------------------------------------------------------------


def _run_doctor(
    argv: list[str],
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = _command(args, stdout=stdout, stderr=stderr, cwd=cwd)
    return code, stdout.getvalue(), stderr.getvalue()


def _patch_stub_checks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    overrides: dict[str, tuple[bool | None, str]] | None = None,
) -> None:
    """Replace ``_build_checks`` with a fixed roster of stub checks.

    Every entry in ``_DEFAULT_CHECK_NAMES`` gets a stub with the
    ``overrides[name]`` outcome (defaulting to ``(True, "ok")``). The
    spec's 12-name ordering is preserved so output assertions remain
    stable.
    """
    overrides = overrides or {}

    def _factory(*, cwd: Path) -> list[Any]:
        del cwd
        return [
            _StubCheck(name=name, outcome=overrides.get(name, (True, "ok")))
            for name in _DEFAULT_CHECK_NAMES
        ]

    monkeypatch.setattr(doctor_cmd, "_build_checks", _factory)


class TestCommandIntegration:
    def test_default_all_pass_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_stub_checks(monkeypatch)
        code, out, err = _run_doctor(["doctor"], cwd=tmp_path)
        assert code == doctor_cmd.EXIT_OK
        assert err == ""
        assert "Summary: 12 passed" in out

    def test_default_one_failure_exits_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_stub_checks(
            monkeypatch,
            overrides={"project_structure": (False, "src/<pkg>/main.py not found")},
        )
        code, out, _err = _run_doctor(["doctor"], cwd=tmp_path)
        assert code == doctor_cmd.EXIT_FAIL
        assert "1 failed" in out

    def test_skip_flag_marks_as_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_stub_checks(monkeypatch)
        code, out, _err = _run_doctor(
            ["doctor", "--skip", "python_version"],
            cwd=tmp_path,
        )
        assert code == doctor_cmd.EXIT_OK
        # python_version still shows up in the report with --skip text.
        assert "python_version" in out
        assert "skipped (via --skip)" in out

    def test_skip_flag_repeatable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_stub_checks(monkeypatch)
        code, out, _err = _run_doctor(
            [
                "doctor",
                "--skip",
                "python_version",
                "--skip",
                "ajolopy_installed",
            ],
            cwd=tmp_path,
        )
        assert code == doctor_cmd.EXIT_OK
        # Both names are surfaced as skipped in the summary.
        assert "10 passed" in out
        assert "2 skipped" in out

    def test_unknown_skip_value_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_stub_checks(monkeypatch)
        code, _out, err = _run_doctor(
            ["doctor", "--skip", "not-a-check"],
            cwd=tmp_path,
        )
        assert code == doctor_cmd.EXIT_FAIL
        assert "not-a-check" in err
        assert "Known names" in err

    def test_warning_does_not_flip_exit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_stub_checks(
            monkeypatch,
            overrides={"env_file_present": (None, ".env not found (using defaults)")},
        )
        code, out, _err = _run_doctor(["doctor"], cwd=tmp_path)
        assert code == doctor_cmd.EXIT_OK
        assert "1 warnings" in out


# ---------------------------------------------------------------------------
# Spec: total run completes in <30 seconds even with every check engaged.
# We assert against a much tighter bound (1s) when every check is mocked,
# which is what CI will actually observe.
# ---------------------------------------------------------------------------


class TestTotalRuntime:
    async def test_runner_under_one_second_with_mocked_checks(self) -> None:
        # 12 fast stubs at < 2ms apiece should finish well under 1s; this
        # is the regression guard for the spec's "<30s" upper bound.
        checks = [_StubCheck(name=name, outcome=(True, "ok")) for name in _DEFAULT_CHECK_NAMES]
        started = time.perf_counter()
        report = await _run_checks(checks, skip=frozenset())
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0
        assert report.passed == 12


# ---------------------------------------------------------------------------
# CheckResult is a frozen dataclass — defensive: order + field shape.
# ---------------------------------------------------------------------------


class TestCheckResultShape:
    def test_fields_present_in_documented_order(self) -> None:
        result = CheckResult(name="x", passed=True, status="ok", message="ok", duration_ms=1.0)
        assert result.name == "x"
        assert result.passed is True
        assert result.status == "ok"
        assert result.message == "ok"
        assert result.duration_ms == 1.0

    def test_report_exit_code_property(self) -> None:
        report = _RunReport(
            results=(),
            passed=0,
            failed=1,
            warnings=0,
            skipped=0,
        )
        assert report.exit_code == doctor_cmd.EXIT_FAIL
        ok_report = _RunReport(
            results=(),
            passed=1,
            failed=0,
            warnings=0,
            skipped=0,
        )
        assert ok_report.exit_code == doctor_cmd.EXIT_OK
