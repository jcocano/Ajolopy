"""``--dry-run`` flow: prompt, decline, --ci variant, unknown-model line."""

import builtins
import io
import json
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import eval as eval_cmd
from ajolopy.cli.dispatcher import build_parser
from ajolopy.observability.pricing import Catalog, ModelPrice, set_default_catalog


def _run(argv: list[str]) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = eval_cmd._command(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def known_catalog() -> Any:
    """Install a tiny catalog so the dry-run estimate is deterministic."""
    catalog = Catalog(
        {
            "claude-sonnet-4-7": ModelPrice(
                input_cost_per_token=0.000_003,
                output_cost_per_token=0.000_015,
            )
        }
    )
    set_default_catalog(catalog)
    yield
    set_default_catalog(None)


class TestPromptAccepted:
    def test_user_typing_y_proceeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
        known_catalog: Any,
    ) -> None:
        _ = known_catalog
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(builtins, "input", lambda _prompt: "y")  # pyright: ignore[reportUnknownLambdaType]
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--dry-run",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        assert "Proceed?" not in out  # the prompt itself is on stdin
        assert "Total" in out  # estimate table was printed


class TestPromptDeclined:
    def test_user_typing_n_exits_declined(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
        known_catalog: Any,
    ) -> None:
        _ = known_catalog
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(builtins, "input", lambda _prompt: "n")  # pyright: ignore[reportUnknownLambdaType]
        code, _out, _err = _run(
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

    def test_user_typing_blank_exits_declined(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
        known_catalog: Any,
    ) -> None:
        _ = known_catalog
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
        monkeypatch.setattr(builtins, "input", lambda _prompt: "")  # pyright: ignore[reportUnknownLambdaType]
        code, _out, _err = _run(
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


class TestDryRunCI:
    def test_ci_variant_emits_json_and_skips_prompt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
        known_catalog: Any,
    ) -> None:
        _ = known_catalog
        monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)

        called: list[str] = []

        def _refuse_input(_prompt: str) -> str:
            called.append(_prompt)
            return "y"

        monkeypatch.setattr(builtins, "input", _refuse_input)
        code, out, _err = _run(
            [
                "eval",
                "tests.cli.eval.fixtures.simple_pkg:PackageLevelSuiteA",
                "--dry-run",
                "--ci",
                "--save-dir",
                str(tmp_path),
                "--no-save",
            ]
        )
        assert code == eval_cmd.EXIT_OK
        payload = json.loads(out)
        assert payload["dry_run"] is True
        assert payload["schema_version"] == 1
        assert called == []
        # The run should NOT have executed under --dry-run --ci.
        assert "PackageLevelSuiteA" in {s["name"] for s in payload["suites"]}


class TestUnknownModel:
    def test_unknown_model_emits_unknown_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_runner_factory: Any,
    ) -> None:
        # No catalog override → ``claude-sonnet-4-7`` is in the default
        # snapshot, so to force the unknown branch we install an empty
        # catalog.
        set_default_catalog(Catalog({}))
        try:
            monkeypatch.setattr(eval_cmd, "EvalRunner", fake_runner_factory)
            monkeypatch.setattr(builtins, "input", lambda _prompt: "n")  # pyright: ignore[reportUnknownLambdaType]
            code, out, _err = _run(
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
            assert "unknown" in out.lower()
        finally:
            set_default_catalog(None)
