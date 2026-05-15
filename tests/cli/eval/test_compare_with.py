"""``--compare-with`` resolution: ``last``, timestamp prefix, and directory path."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser
from ajolopy.eval.storage import save_eval_run
from tests.cli.eval.conftest import make_eval_run


def _run(argv: list[str]) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _seed_prior_run(
    save_dir: Path,
    *,
    suite: str,
    timestamp: str,
    aggregate_score: float = 0.95,
    metric_aggregates: dict[str, float] | None = None,
    dataset_sha256: str | None = "feedfeed",
) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    run = make_eval_run(
        suite,
        timestamp=timestamp,
        aggregate_score=aggregate_score,
        metric_aggregates=metric_aggregates,
        dataset_sha256=dataset_sha256,
    )
    return save_eval_run(run, save_dir / f"{timestamp}-{suite}.json")


class TestLast:
    def test_last_picks_most_recent_matching_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        _seed_prior_run(
            tmp_path,
            suite="PackageLevelSuiteA",
            timestamp="2026-05-14T20-00-00Z",
            aggregate_score=0.95,
        )
        _seed_prior_run(
            tmp_path,
            suite="PackageLevelSuiteA",
            timestamp="2026-05-14T21-00-00Z",
            aggregate_score=0.85,
        )
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(eval_cmd, "_invocation_timestamp", lambda: "2026-05-14T22-30-00Z")
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--compare-with",
                "last",
                "--ci",
                "--save-dir",
                str(tmp_path),
            ]
        )
        # No regression: the current run uses the default 0.9 aggregate
        # which beats neither 0.95 (regression) nor the 0.85 (no
        # regression). Default mock = 0.9 vs prior 0.85 (most recent
        # before current) → no regression → exit 0.
        assert code == eval_cmd.EXIT_OK

    def test_last_detects_regression_against_most_recent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        _seed_prior_run(
            tmp_path,
            suite="PackageLevelSuiteA",
            timestamp="2026-05-14T21-00-00Z",
            metric_aggregates={"helpful": 0.99},
        )

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            inst.set_run(
                "PackageLevelSuiteA",
                make_eval_run(
                    "PackageLevelSuiteA",
                    passed=True,
                    aggregate_score=0.85,
                    metric_aggregates={"helpful": 0.85},
                ),
            )
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        monkeypatch.setattr(eval_cmd, "_invocation_timestamp", lambda: "2026-05-14T22-30-00Z")
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--compare-with",
                "last",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        # Per-suite passed=True; regression should still force exit 1.
        assert code == eval_cmd.EXIT_FAILED
        assert "REGRESSION" in out or "regressed" in out


class TestTimestampPrefix:
    def test_exact_timestamp_prefix_picks_matching_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        _seed_prior_run(
            tmp_path,
            suite="PackageLevelSuiteA",
            timestamp="2026-05-14T19-00-00Z",
            metric_aggregates={"helpful": 0.95},
        )
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--compare-with",
                "2026-05-14T19-00-00Z",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        # default mock aggregate is 0.9; prior is 0.95 -> regression -> exit 1
        assert code == eval_cmd.EXIT_FAILED


class TestDirectoryPath:
    def test_directory_path_reads_from_alternative_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        save_dir = tmp_path / "save"
        prior_dir = tmp_path / "prior"
        _seed_prior_run(
            prior_dir,
            suite="PackageLevelSuiteA",
            timestamp="2026-05-14T18-00-00Z",
            metric_aggregates={"helpful": 0.99},
        )
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--compare-with",
                str(prior_dir),
                "--ci",
                "--save-dir",
                str(save_dir),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_FAILED


class TestNoPriorRun:
    def test_suite_without_prior_run_is_new(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        parser = build_parser()
        args = parser.parse_args(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--compare-with",
                "last",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
        payload = json.loads(stdout.getvalue())
        assert code == eval_cmd.EXIT_OK
        assert payload["suites"][0]["compared_with"] is None

    def test_new_badge_appears_in_default_output(
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
                "--compare-with",
                "last",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert "NEW" in out


class TestComparisonErrors:
    def test_dataset_sha_mismatch_emits_stderr_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        _seed_prior_run(
            tmp_path,
            suite="PackageLevelSuiteA",
            timestamp="2026-05-14T17-00-00Z",
            dataset_sha256="aaaaaaaa",
        )

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            inst.set_run(
                "PackageLevelSuiteA",
                make_eval_run(
                    "PackageLevelSuiteA",
                    dataset_sha256="bbbbbbbb",
                ),
            )
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, _out, err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--compare-with",
                "2026-05-14T17-00-00Z",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert "skipping comparison" in err
