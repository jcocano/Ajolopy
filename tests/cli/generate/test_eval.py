"""Acceptance: ``ajolopy generate eval <name>`` produces a pair of files."""

import ast
import json
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_eval_writes_py_module_and_dataset(fake_project: Path) -> None:
    result = invoke_generate(["eval", "support"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    py_target = fake_project / "evals" / "support_eval.py"
    dataset_target = fake_project / "evals" / "datasets" / "support.jsonl"
    assert py_target.is_file()
    assert dataset_target.is_file()

    py_text = py_target.read_text(encoding="utf-8")
    ast.parse(py_text)
    assert "@Eval" in py_text
    assert "class SupportEval" in py_text
    # The agent import points at the auto-detected package.
    assert "from myapp.agents.support import Support" in py_text


def test_eval_dataset_contains_one_placeholder_case(fake_project: Path) -> None:
    result = invoke_generate(["eval", "support"])
    assert result.exit_code == generate_cmd.EXIT_OK

    dataset_target = fake_project / "evals" / "datasets" / "support.jsonl"
    lines = [
        line for line in dataset_target.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 1
    case = json.loads(lines[0])
    assert "input" in case
    assert "expected" in case


def test_eval_reports_both_files_to_stdout(fake_project: Path) -> None:
    _ = fake_project
    result = invoke_generate(["eval", "support"])
    stdout = result.stdout.replace("\\", "/")
    assert "evals/support_eval.py" in stdout
    assert "evals/datasets/support.jsonl" in stdout
