"""Validation paths: unknown kinds, non-snake names, exit-code surface."""

from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate


class TestBadKind:
    """Unknown ``kind`` arguments must be rejected at the entry point."""

    def test_unknown_kind_is_rejected_with_usage_exit(self, fake_project: Path) -> None:
        _ = fake_project
        result = invoke_generate(["bogus", "name"])
        assert result.exit_code == generate_cmd.EXIT_USAGE
        assert "unknown kind" in result.stderr
        # The error message lists every valid kind so the user can recover.
        for kind in generate_cmd.SUPPORTED_KINDS:
            assert kind in result.stderr


class TestBadName:
    """Names that don't match the snake_case regex are rejected."""

    def test_pascal_case_name_is_rejected(self, fake_project: Path) -> None:
        _ = fake_project
        result = invoke_generate(["agent", "BadName"])
        assert result.exit_code == generate_cmd.EXIT_USAGE
        assert "snake_case" in result.stderr

    def test_leading_digit_is_rejected(self, fake_project: Path) -> None:
        _ = fake_project
        result = invoke_generate(["agent", "1bad"])
        assert result.exit_code == generate_cmd.EXIT_USAGE
        assert "snake_case" in result.stderr

    def test_kebab_case_name_is_rejected(self, fake_project: Path) -> None:
        _ = fake_project
        result = invoke_generate(["agent", "bad-name"])
        assert result.exit_code == generate_cmd.EXIT_USAGE
        assert "snake_case" in result.stderr


class TestExitCodes:
    """Module-level constants stay aligned with the documented codes."""

    def test_documented_exit_codes(self) -> None:
        assert generate_cmd.EXIT_OK == 0
        assert generate_cmd.EXIT_NO_PROJECT == 1
        assert generate_cmd.EXIT_EXISTS == 1
        assert generate_cmd.EXIT_USAGE == 2


class TestSupportedKinds:
    """The seven documented kinds are all wired into the dispatch table."""

    def test_seven_kinds_supported(self) -> None:
        assert set(generate_cmd.SUPPORTED_KINDS) == {
            "agent",
            "tool",
            "workflow",
            "eval",
            "controller",
            "module",
            "service",
        }
