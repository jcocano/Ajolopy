"""Acceptance: ``ajolopy generate tool <name>`` scaffolds a standalone tool."""

import ast
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_tool_writes_standalone_stub_under_tools_dir(fake_project: Path) -> None:
    result = invoke_generate(["tool", "foo"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "tools" / "foo.py"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    ast.parse(text)
    assert "@Tool" in text
    assert "def foo(" in text
