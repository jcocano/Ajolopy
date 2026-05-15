"""Acceptance: ``ajolopy generate controller <name>`` scaffolds an @Controller."""

import ast
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_controller_emits_get_and_post_stubs(fake_project: Path) -> None:
    result = invoke_generate(["controller", "users"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "controllers" / "users_controller.py"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    ast.parse(text)
    assert '@Controller("/users")' in text
    assert "@Get" in text
    assert "@Post" in text
    assert "class UsersController" in text
