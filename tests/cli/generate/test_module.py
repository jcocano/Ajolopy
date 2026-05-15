"""Acceptance: ``ajolopy generate module <name>`` produces an @Module skeleton."""

import ast
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_module_writes_root_level_skeleton(fake_project: Path) -> None:
    result = invoke_generate(["module", "billing"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "billing_module.py"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    ast.parse(text)
    assert "@Module" in text
    assert "imports=[]" in text
    assert "providers=[]" in text
    assert "controllers=[]" in text
    assert "class BillingModule" in text
