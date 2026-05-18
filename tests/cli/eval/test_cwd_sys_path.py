"""Regression: ``ajolopy eval`` must put cwd on ``sys.path``.

A freshly scaffolded project ships an ``evals/`` package at the
project root. When the user runs ``ajolopy eval`` (default target
``"evals"``) the import succeeds only if the cwd is on
``sys.path``. The console-script entry point does NOT add it,
unlike ``python -m`` invocations. Pytest, pyright, and friends
prepend cwd transparently for the same reason; AJ-89 makes the
``eval`` subcommand do the same.

These tests materialise a throw-away ``evals/`` package in
``tmp_path``, ``chdir`` into it, drive ``_command`` with the
existing test seam, and assert the suite is discovered without
``ModuleNotFoundError``. They also assert the helper is
idempotent and the cleanup leaves ``sys.path`` / ``sys.modules``
in a pristine state for the next test.
"""

import io
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser


def _materialise_evals_pkg(root: Path) -> None:
    """Write a minimal ``evals/`` package with one ``@Eval`` class.

    The class points its dataset at the in-repo
    ``support.jsonl`` fixture (3 cases) so ``--dry-run`` resolves
    a deterministic case count without booting an agent runtime.
    """
    evals_dir = root / "evals"
    evals_dir.mkdir()
    (evals_dir / "__init__.py").write_text("")
    # Point the synthetic suite at the in-repo support.jsonl fixture so
    # ``--dry-run`` resolves a deterministic case count without booting
    # an agent runtime.
    dataset_literal = repr(
        str(Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "support.jsonl")
    )

    (evals_dir / "foo.py").write_text(
        textwrap.dedent(
            f"""
            from collections.abc import Mapping

            from ajolopy.eval.eval_decorator import EVAL_MARKER, EvalMetadata
            from ajolopy.eval.metric import MetricMetadata


            class _Runtime:
                _models = [("claude-opus-4-7", object())]


            class _Agent:
                _agent_runtime = _Runtime()


            def _metric_fn(self, output, expected):  # pragma: no cover - stub
                return 1.0


            class FooEval:
                pass


            setattr(
                FooEval,
                EVAL_MARKER,
                EvalMetadata(
                    suite_cls=FooEval,
                    target_cls=_Agent,
                    target_kind="agent",
                    dataset_spec={dataset_literal},
                    threshold=0.5,
                    concurrency=1,
                    metrics={{
                        "helpful": MetricMetadata(
                            name="helpful",
                            fn=_metric_fn,
                            aggregator="mean",
                            weight=1.0,
                            pass_threshold=0.5,
                            is_async=False,
                        )
                    }},
                ),
            )
            """
        ).lstrip()
    )


@pytest.fixture
def restore_sys_state() -> Any:
    """Snapshot ``sys.path`` + ``sys.modules`` keys; restore on teardown."""
    original_path = list(sys.path)
    original_modules = set(sys.modules)
    yield
    # Drop any path entries the test added (typically just ``""``).
    sys.path[:] = original_path
    # Drop any modules the test imported under the synthetic ``evals``
    # namespace so subsequent tests don't see them.
    for name in list(sys.modules):
        if name not in original_modules and (name == "evals" or name.startswith("evals.")):
            del sys.modules[name]


def _run(argv: list[str]) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestCwdOnSysPath:
    def test_default_target_resolves_local_evals_package(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        restore_sys_state: Any,
    ) -> None:
        """Mimics ``ajolopy eval --ci`` from a fresh project root.

        Before AJ-89 the discovery raised ``ModuleNotFoundError`` for
        ``evals`` because the console-script entry point doesn't put
        cwd on ``sys.path``. After AJ-89 the helper prepends ``""``
        and discovery succeeds.
        """
        _ = restore_sys_state
        _materialise_evals_pkg(tmp_path)
        monkeypatch.chdir(tmp_path)

        # ``--dry-run --ci --no-save`` short-circuits before the runner
        # boots, so we don't need any pricing-catalog or LLM stubbing.
        code, out, err = _run(["eval", "--dry-run", "--ci", "--no-save"])

        assert code == eval_cmd.EXIT_OK, err
        assert "No module named 'evals'" not in err
        assert "FooEval" in out

    def test_explicit_target_also_resolves_from_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        restore_sys_state: Any,
    ) -> None:
        """An explicit ``evals.foo:FooEval`` target benefits too."""
        _ = restore_sys_state
        _materialise_evals_pkg(tmp_path)
        monkeypatch.chdir(tmp_path)

        code, out, err = _run(["eval", "evals.foo:FooEval", "--dry-run", "--ci", "--no-save"])

        assert code == eval_cmd.EXIT_OK, err
        assert "FooEval" in out


class TestHelperIdempotent:
    def test_repeated_calls_do_not_stack_duplicates(
        self,
        restore_sys_state: Any,
    ) -> None:
        """``_ensure_cwd_on_sys_path`` must not insert ``""`` twice."""
        _ = restore_sys_state
        # Force a known starting state: no ``""`` on sys.path.
        sys.path[:] = [p for p in sys.path if p != ""]
        cwd = str(Path.cwd())
        sys.path[:] = [p for p in sys.path if p != cwd]

        eval_cmd._ensure_cwd_on_sys_path()
        eval_cmd._ensure_cwd_on_sys_path()
        eval_cmd._ensure_cwd_on_sys_path()

        assert sys.path.count("") == 1

    def test_no_insert_when_empty_already_present(
        self,
        restore_sys_state: Any,
    ) -> None:
        """If ``""`` is already on ``sys.path`` we leave the list alone."""
        _ = restore_sys_state
        if "" not in sys.path:
            sys.path.insert(0, "")
        before = list(sys.path)

        eval_cmd._ensure_cwd_on_sys_path()

        assert sys.path == before

    def test_no_insert_when_resolved_cwd_already_present(
        self,
        restore_sys_state: Any,
    ) -> None:
        """If the resolved cwd is on ``sys.path`` we skip the insert too."""
        _ = restore_sys_state
        sys.path[:] = [p for p in sys.path if p != ""]
        cwd = str(Path.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        before = list(sys.path)

        eval_cmd._ensure_cwd_on_sys_path()

        assert sys.path == before
