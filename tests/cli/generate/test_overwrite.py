"""Overwrite protection: refuse by default, accept ``--force``."""

from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_existing_target_without_force_returns_exit_exists(fake_project: Path) -> None:
    target = fake_project / "src" / "myapp" / "agents" / "support.py"
    target.parent.mkdir(parents=True)
    target.write_text("# preexisting\n", encoding="utf-8")

    result = invoke_generate(["agent", "support"])
    assert result.exit_code == generate_cmd.EXIT_EXISTS
    assert "refusing to overwrite" in result.stderr
    # The file was not touched.
    assert target.read_text(encoding="utf-8") == "# preexisting\n"


def test_force_overwrites_existing_target(fake_project: Path) -> None:
    target = fake_project / "src" / "myapp" / "agents" / "support.py"
    target.parent.mkdir(parents=True)
    target.write_text("# preexisting\n", encoding="utf-8")

    result = invoke_generate(["agent", "support", "--force"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr
    text = target.read_text(encoding="utf-8")
    assert "preexisting" not in text
    assert "class Support" in text


def test_eval_collision_on_either_file_blocks_both_writes(fake_project: Path) -> None:
    # Pre-seed the dataset half of the pair; the .py file must NOT be
    # written either because the collision is detected during the
    # pre-flight pass.
    dataset = fake_project / "evals" / "datasets" / "support.jsonl"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("# existing\n", encoding="utf-8")

    result = invoke_generate(["eval", "support"])
    assert result.exit_code == generate_cmd.EXIT_EXISTS
    py_target = fake_project / "evals" / "support_eval.py"
    assert not py_target.exists()
    assert dataset.read_text(encoding="utf-8") == "# existing\n"
