"""Discovery semantics: target resolution, dedupe, walking, and exit codes."""

import io
from typing import Any, cast

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser


def _parse(argv: list[str]) -> Any:
    parser = build_parser()
    return parser.parse_args(argv)


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``_command`` with StringIO buffers and return (code, out, err)."""
    args = _parse(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestModuleResolution:
    def test_module_target_discovers_classes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        code, _out, _err = _run(["eval", "tests.cli.eval.fixtures.simple_pkg", "--no-save"])
        assert code == eval_cmd.EXIT_OK

    def test_pkg_class_target_resolves_single_class(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        captured: list[Any] = []
        original = fake_runner_factory

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = original(eval_runs_dir=eval_runs_dir)
            captured.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert len(captured) == 1
        assert [cls.__name__ for cls in captured[0].calls] == ["PackageLevelSuiteA"]

    def test_attribute_not_eval_exits_failed(self) -> None:
        code, _out, err = _run(["eval", "tests.cli.eval.fixtures.no_eval:NOT_AN_EVAL"])
        assert code == eval_cmd.EXIT_FAILED
        assert "not an @Eval" in err.lower() or "@eval" in err.lower()

    def test_attribute_missing_exits_failed(self) -> None:
        code, _out, err = _run(["eval", "tests.cli.eval.fixtures.simple_pkg:Nope"])
        assert code == eval_cmd.EXIT_FAILED
        assert "attribute not found" in err

    def test_package_walks_submodules(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        captured: list[Any] = []
        original = fake_runner_factory

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = original(eval_runs_dir=eval_runs_dir)
            captured.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, _out, _err = _run(["eval", "tests.cli.eval.fixtures.simple_pkg", "--no-save"])
        assert code == eval_cmd.EXIT_OK
        names = [cls.__name__ for cls in captured[0].calls]
        assert "SubmoduleSuite" in names
        assert "PackageLevelSuiteA" in names
        assert "PackageLevelSuiteB" in names

    def test_declaration_order_preserved(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        captured: list[Any] = []
        original = fake_runner_factory

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = original(eval_runs_dir=eval_runs_dir)
            captured.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, _out, _err = _run(["eval", "tests.cli.eval.fixtures.simple_pkg", "--no-save"])
        assert code == eval_cmd.EXIT_OK
        names = [cls.__name__ for cls in captured[0].calls]
        # Package-level classes (in declaration order) come first; the
        # walker processes the parent module before its submodules.
        assert names.index("PackageLevelSuiteA") < names.index("PackageLevelSuiteB")
        assert names.index("PackageLevelSuiteB") < names.index("SubmoduleSuite")


class TestDedupe:
    def test_two_targets_same_class_runs_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        captured: list[Any] = []
        original = fake_runner_factory

        def factory(*, eval_runs_dir: Any = None) -> Any:
            inst = original(eval_runs_dir=eval_runs_dir)
            captured.append(inst)
            return inst

        monkeypatch.setattr(eval_cmd, "EvalRunner", factory)
        code, _out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert [cls.__name__ for cls in captured[0].calls] == ["PackageLevelSuiteA"]


class TestImportFailures:
    def test_nonexistent_module_exits_failed(self) -> None:
        code, _out, err = _run(["eval", "tests.cli.eval.fixtures.nonexistent_xyz"])
        assert code == eval_cmd.EXIT_FAILED
        assert "tests.cli.eval.fixtures.nonexistent_xyz" in err


class TestZeroSuites:
    def test_empty_package_exits_discovery(self) -> None:
        code, _out, err = _run(["eval", "tests.cli.eval.fixtures.no_eval"])
        assert code == eval_cmd.EXIT_DISCOVERY
        assert "no eval suites discovered" in err.lower()


class TestDefaultTarget:
    def test_no_argument_defaults_to_evals(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no TARGET is given, the CLI imports ``evals``.

        We exercise the default-resolution branch by asserting the
        command tries to import that exact module and surfaces an
        ImportError when it does not exist in this repo.
        """
        captured: list[str] = []

        def fake_import(name: str) -> Any:
            captured.append(name)
            raise ImportError(f"No module named {name!r}")

        monkeypatch.setattr("ajolopy.cli.commands.eval.importlib.import_module", fake_import)
        code, _out, _err = _run(["eval"])
        assert code == eval_cmd.EXIT_FAILED
        assert captured == ["evals"]
        # Silence unused-cast lint.
        _ = cast
