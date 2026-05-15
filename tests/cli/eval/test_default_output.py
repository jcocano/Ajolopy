"""Default rendering: emoji + ANSI on TTY, ASCII badges off TTY."""

import io
from pathlib import Path
from typing import Any, override

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser
from tests.cli.eval.conftest import make_eval_run


class _TTYWrapper(io.StringIO):
    """StringIO that lies about being a TTY for the ANSI-render branch."""

    @override
    def isatty(self) -> bool:
        return True


def _run(argv: list[str], *, tty: bool = False) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout: io.StringIO = _TTYWrapper() if tty else io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestPlainOutput:
    def test_non_tty_uses_ascii_badges(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert "[PASS]" in out
        # No ANSI escape sequences on a non-TTY stream.
        assert "\x1b[" not in out

    def test_per_suite_line_contains_name_score_threshold_cases(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        runners: list[Any] = []

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            inst.set_run(
                "PackageLevelSuiteA",
                make_eval_run(
                    "PackageLevelSuiteA",
                    aggregate_score=0.875,
                    threshold=0.5,
                    cases=4,
                ),
            )
            runners.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert "PackageLevelSuiteA" in out
        assert "0.875" in out
        assert "0.500" in out
        assert "[4 cases]" in out

    def test_summary_counts_passed_and_failed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            inst.set_run(
                "PackageLevelSuiteA",
                make_eval_run("PackageLevelSuiteA", passed=False, aggregate_score=0.1),
            )
            inst.set_run(
                "PackageLevelSuiteB",
                make_eval_run("PackageLevelSuiteB", passed=True, aggregate_score=0.9),
            )
            inst.set_run(
                "SubmoduleSuite",
                make_eval_run("SubmoduleSuite", passed=True, aggregate_score=0.9),
            )
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_FAILED
        assert "Summary: 2 passed, 1 failed" in out
        assert "Exit code: 1" in out

    def test_final_exit_code_line_matches_return_value(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert f"Exit code: {code}" in out


class TestTTYOutput:
    def test_tty_emits_ansi_and_emoji(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ],
            tty=True,
        )
        assert code == eval_cmd.EXIT_OK
        # ANSI escape introducer
        assert "\x1b[" in out
        # ``✅`` glyph for the pass case
        assert "✅" in out
