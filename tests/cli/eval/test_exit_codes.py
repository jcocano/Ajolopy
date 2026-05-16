"""Exit codes: 0 / 1 / 2 / 3 / 4 paths covered by happy + failure scenarios."""

import builtins
import contextlib
import io
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser
from ajolopy.observability.pricing import Catalog, ModelPrice, set_default_catalog
from tests.cli.eval.conftest import make_eval_run


def _run(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    return eval_cmd._command(args, stdout=stdout, stderr=stderr)


class TestExitCodes:
    def test_all_passing_returns_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK

    def test_failing_suite_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            inst.set_run(
                "PackageLevelSuiteA",
                make_eval_run(
                    "PackageLevelSuiteA",
                    passed=False,
                    aggregate_score=0.1,
                ),
            )
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_FAILED

    def test_bad_threshold_arg_exits_two(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _run(
                [
                    "eval",
                    "tests.cli.eval.fixtures.simple_pkg",
                    "--threshold-override",
                    "9.5",
                ]
            )
        assert excinfo.value.code == eval_cmd.EXIT_USAGE

    def test_zero_suites_returns_three(self) -> None:
        code = _run(["eval", "tests.cli.eval.fixtures.no_eval"])
        assert code == eval_cmd.EXIT_DISCOVERY

    def test_dry_run_declined_returns_four(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        set_default_catalog(
            Catalog(
                {
                    "claude-opus-4-7": ModelPrice(
                        input_cost_per_token=0.0,
                        output_cost_per_token=0.0,
                    )
                }
            )
        )
        try:
            monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
            monkeypatch.setattr(builtins, "input", lambda _prompt: "no")  # pyright: ignore[reportUnknownLambdaType]
            code = _run(
                [
                    "eval",
                    "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                    "--dry-run",
                    "--save-dir",
                    str(tmp_path),
                    "--no-save",
                ]
            )
            assert code == eval_cmd.EXIT_DRY_RUN_DECLINED
        finally:
            set_default_catalog(None)


class TestHelp:
    def test_eval_help_lists_every_flag(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from ajolopy.cli import main as cli_main

        with contextlib.suppress(SystemExit):
            cli_main(["eval", "--help"])
        out = capsys.readouterr().out
        for flag in (
            "--filter",
            "--ci",
            "--compare-with",
            "--threshold-override",
            "--dry-run",
            "--save-dir",
            "--no-save",
        ):
            assert flag in out

    def test_root_help_lists_eval(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from ajolopy.cli import main as cli_main

        with contextlib.suppress(SystemExit):
            cli_main(["--help"])
        out = capsys.readouterr().out
        assert "eval" in out
