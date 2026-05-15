"""``--ci`` mode: JSON shape, schema_version, per-suite blocks, exit_code field."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser
from tests.cli.eval.conftest import make_eval_run


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    raw = stdout.getvalue().strip()
    return code, json.loads(raw), stderr.getvalue()


class TestCIOutput:
    def test_top_level_schema_version_is_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, payload, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert payload["schema_version"] == 1

    def test_top_level_counts_match_per_suite_blocks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            inst.set_run(
                "PackageLevelSuiteA",
                make_eval_run("PackageLevelSuiteA", passed=True),
            )
            inst.set_run(
                "PackageLevelSuiteB",
                make_eval_run("PackageLevelSuiteB", passed=False, aggregate_score=0.1),
            )
            inst.set_run(
                "SubmoduleSuite",
                make_eval_run("SubmoduleSuite", passed=True),
            )
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, payload, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_FAILED
        assert payload["passed"] == 2
        assert payload["failed"] == 1
        assert payload["exit_code"] == code

    def test_compared_with_null_without_compare_flag(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        _code, payload, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        suite = payload["suites"][0]
        assert suite["compared_with"] is None
        assert suite["regressions"] == []

    def test_suite_block_carries_metrics(
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
                    metric_aggregates={"helpful": 0.9, "safe": 1.0},
                ),
            )
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        _code, payload, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        suite = payload["suites"][0]
        assert set(suite["metrics"]) == {"helpful", "safe"}
        assert suite["metrics"]["helpful"]["aggregator"] == "mean"
        assert suite["metrics"]["helpful"]["aggregate"] == 0.9
