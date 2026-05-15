"""Acceptance: ``ajolopy generate service <name>`` produces an @Injectable skeleton."""

import ast
from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


def test_service_writes_injectable_skeleton(fake_project: Path) -> None:
    result = invoke_generate(["service", "notifier"])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr

    target = fake_project / "src" / "myapp" / "services" / "notifier_service.py"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    ast.parse(text)
    assert "@Injectable" in text
    assert "class NotifierService" in text
