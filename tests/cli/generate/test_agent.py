"""Acceptance: ``ajolopy generate agent <name>`` scaffolds an @Agent shell."""

import ast
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_agent_default_path_renders_pascal_case_class(fake_project: Path) -> None:
    result = invoke_generate(["agent", "support"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "agents" / "support.py"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "class Support" in text
    assert "@Agent" in text
    assert "@Tool" in text


def test_agent_file_is_syntactically_valid_python(fake_project: Path) -> None:
    result = invoke_generate(["agent", "billing_assistant"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "agents" / "billing_assistant.py"
    text = target.read_text(encoding="utf-8")
    # ``ast.parse`` raises on bad syntax — the assertion is implicit.
    ast.parse(text)
    # Multi-word names produce ``BillingAssistant``.
    assert "class BillingAssistant" in text


def test_agent_reports_relative_path_to_stdout(fake_project: Path) -> None:
    _ = fake_project
    result = invoke_generate(["agent", "support"])
    assert result.exit_code == generate_cmd.EXIT_OK
    assert "src/myapp/agents/support.py" in result.stdout.replace("\\", "/")
