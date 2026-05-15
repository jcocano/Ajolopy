"""Run + persist semantics: save-dir, no-save, shared timestamp, threshold override."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser
from ajolopy.eval.eval_decorator import EVAL_MARKER


def _run(argv: list[str]) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestPersistence:
    def test_save_dir_writes_one_file_per_suite(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(eval_cmd, "_invocation_timestamp", lambda: "2026-05-14T22-30-00Z")
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
            ]
        )
        assert code == eval_cmd.EXIT_OK
        files = sorted(p.name for p in tmp_path.glob("*.json"))
        assert "2026-05-14T22-30-00Z-PackageLevelSuiteA.json" in files
        assert "2026-05-14T22-30-00Z-PackageLevelSuiteB.json" in files
        assert "2026-05-14T22-30-00Z-SubmoduleSuite.json" in files

    def test_all_suites_share_invocation_timestamp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(eval_cmd, "_invocation_timestamp", lambda: "2026-05-14T22-31-00Z")
        _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
            ]
        )
        prefixes = {p.name[:20] for p in tmp_path.glob("*.json")}
        assert prefixes == {"2026-05-14T22-31-00Z"}

    def test_no_save_writes_zero_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert list(tmp_path.glob("*.json")) == []

    def test_saved_payload_is_loadable_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(eval_cmd, "_invocation_timestamp", lambda: "2026-05-14T22-32-00Z")
        _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--save-dir",
                str(tmp_path),
            ]
        )
        target = tmp_path / "2026-05-14T22-32-00Z-PackageLevelSuiteA.json"
        payload = json.loads(target.read_text())
        assert payload["schema_version"] == 1
        assert payload["suite"] == "PackageLevelSuiteA"


class TestThresholdOverride:
    def test_threshold_override_seen_by_runner(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        captured: list[Any] = []

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            captured.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--threshold-override",
                "0.9",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert captured[0].observed_thresholds == [0.9]

    def test_original_metadata_unchanged_after_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        from tests.cli.eval.fixtures.simple_pkg import PackageLevelSuiteA

        original_threshold = getattr(PackageLevelSuiteA, EVAL_MARKER).threshold
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--threshold-override",
                "0.99",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        # The class's metadata stays bound to the original threshold —
        # the override lives on a transient subclass.
        assert getattr(PackageLevelSuiteA, EVAL_MARKER).threshold == original_threshold

    def test_threshold_above_one_exits_usage(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _run(
                [
                    "eval",
                    "tests.cli.eval.fixtures.simple_pkg",
                    "--threshold-override",
                    "1.5",
                ]
            )
        assert excinfo.value.code == eval_cmd.EXIT_USAGE

    def test_threshold_negative_exits_usage(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _run(
                [
                    "eval",
                    "tests.cli.eval.fixtures.simple_pkg",
                    "--threshold-override",
                    "-0.1",
                ]
            )
        assert excinfo.value.code == eval_cmd.EXIT_USAGE


class TestOrdering:
    def test_suites_run_in_declaration_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        captured: list[Any] = []

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = fake_runner_factory(eval_runs_dir=eval_runs_dir)
            captured.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        names = [cls.__name__ for cls in captured[0].calls]
        # First package-level suite must precede the second; both must
        # precede the submodule discovery output (the walker walks
        # parent → submodule order).
        assert names.index("PackageLevelSuiteA") < names.index("PackageLevelSuiteB")
        assert names.index("PackageLevelSuiteB") < names.index("SubmoduleSuite")
