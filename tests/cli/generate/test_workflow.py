"""Acceptance: ``ajolopy generate workflow <name>`` writes the @Workflow shell."""

import ast
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_workflow_emits_two_agent_placeholders(fake_project: Path) -> None:
    result = invoke_generate(["workflow", "team"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "workflows" / "team.py"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    ast.parse(text)
    assert "@Workflow" in text
    assert text.count("@Agent") == 2
    assert "class TeamTriage" in text
    assert "class TeamWorker" in text
    assert "class Team" in text
