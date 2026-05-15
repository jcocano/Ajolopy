"""Filter semantics: fnmatch case-insensitive matching + empty-match exit."""

import io
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser


def _run(argv: list[str]) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestFilter:
    def test_pattern_keeps_matching_suites(
        self,
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
                "tests.cli.eval.fixtures.simple_pkg",
                "--filter",
                "Package*",
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        names = [cls.__name__ for cls in captured[0].calls]
        assert all(n.startswith("PackageLevelSuite") for n in names)
        assert "SubmoduleSuite" not in names

    def test_filter_is_case_insensitive(
        self,
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
                "tests.cli.eval.fixtures.simple_pkg",
                "--filter",
                "PACKAGE*",
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        names = [cls.__name__ for cls in captured[0].calls]
        # The mixed-case ``PackageLevelSuiteA/B`` classes match the
        # uppercase pattern after lowercasing.
        assert any("Package" in n for n in names)

    def test_wildcard_keeps_every_suite(
        self,
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
                "tests.cli.eval.fixtures.simple_pkg",
                "--filter",
                "*",
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert len(captured[0].calls) >= 3

    def test_empty_match_exits_failed(self) -> None:
        code, _out, err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg",
                "--filter",
                "Nothing*",
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_FAILED
        assert "no suites matched filter" in err
