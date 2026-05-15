"""CLI validation: kebab-case enforcement, traversal rejection, dir collision."""

from pathlib import Path

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import CommandResult, invoke_new


class TestKebabCase:
    """``^[a-z][a-z0-9-]{1,40}$`` is rejected at the entry point."""

    def test_capitalised_name_is_rejected(self, tmp_cwd: Path) -> None:
        result = invoke_new(["MyAgent", "--yes"])
        assert result.exit_code == new_cmd.EXIT_USAGE
        assert "kebab-case" in result.stderr
        assert not (tmp_cwd / "MyAgent").exists()

    def test_snake_case_name_is_rejected(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my_agent", "--yes"])
        assert result.exit_code == new_cmd.EXIT_USAGE
        assert "kebab-case" in result.stderr
        assert not (tmp_cwd / "my_agent").exists()

    def test_leading_digit_is_rejected(self, tmp_cwd: Path) -> None:
        result = invoke_new(["1abc", "--yes"])
        assert result.exit_code == new_cmd.EXIT_USAGE
        assert "kebab-case" in result.stderr
        assert not (tmp_cwd / "1abc").exists()

    def test_lowercase_kebab_name_is_accepted(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        assert (tmp_cwd / "my-agent").is_dir()


class TestPathTraversal:
    """A project name must never escape the cwd."""

    def test_dot_dot_segment_is_rejected(self, tmp_cwd: Path) -> None:
        result = invoke_new(["../bad", "--yes"])
        assert result.exit_code == new_cmd.EXIT_USAGE
        # The kebab-case regex rejects ``..`` first, so accept either
        # the kebab-case or the traversal-specific message.
        assert "kebab-case" in result.stderr or "path separators" in result.stderr

    def test_slash_segment_is_rejected(self, tmp_cwd: Path) -> None:
        result = invoke_new(["foo/bar", "--yes"])
        assert result.exit_code == new_cmd.EXIT_USAGE

    def test_absolute_path_is_rejected(self, tmp_cwd: Path, tmp_path: Path) -> None:
        _ = tmp_cwd
        result = invoke_new([str(tmp_path / "abs-target"), "--yes"])
        assert result.exit_code == new_cmd.EXIT_USAGE


class TestDestinationExists:
    """An already-existing destination directory aborts the command."""

    def test_existing_directory_exits_one(self, tmp_cwd: Path) -> None:
        existing = tmp_cwd / "my-agent"
        existing.mkdir()
        (existing / "sentinel.txt").write_text("dont touch me", encoding="utf-8")

        result = invoke_new(["my-agent", "--yes"])
        assert result.exit_code == new_cmd.EXIT_FAILED
        assert "already exists" in result.stderr
        # The sentinel file survives -- the command never touched it.
        assert (existing / "sentinel.txt").read_text(encoding="utf-8") == "dont touch me"


class TestExitCodeConstants:
    """Module-level constants stay aligned with the documented codes."""

    def test_documented_exit_codes(self) -> None:
        assert new_cmd.EXIT_OK == 0
        assert new_cmd.EXIT_FAILED == 1
        assert new_cmd.EXIT_USAGE == 2
        assert new_cmd.EXIT_INTERRUPTED == 130


def test_successful_run_emits_next_steps_block(tmp_cwd: Path) -> None:
    """Acceptance: the generation log ends with the documented next-steps."""
    result: CommandResult = invoke_new(["my-agent", "--yes"])
    assert result.exit_code == new_cmd.EXIT_OK
    assert "Next steps:" in result.stdout
    assert "cd my-agent" in result.stdout
    assert "uv sync" in result.stdout
    assert "cp .env.example .env" in result.stdout
    assert "ajolopy dev" in result.stdout
