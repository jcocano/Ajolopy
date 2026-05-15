"""Generated tree assertions: documented files exist with expected content."""

from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new


@pytest.fixture
def generated(tmp_cwd: Path) -> Path:
    """Generate a default ``--yes`` project once per test."""
    result = invoke_new(["my-agent", "--yes"])
    assert result.exit_code == new_cmd.EXIT_OK, result.stderr
    return tmp_cwd / "my-agent"


class TestExpectedFiles:
    """Each file listed in the spec is present on disk after generation."""

    def test_all_documented_paths_exist(self, generated: Path) -> None:
        expected: list[str] = [
            "pyproject.toml",
            "README.md",
            ".env.example",
            ".gitignore",
            "Dockerfile",
            "src/my_agent/__init__.py",
            "src/my_agent/main.py",
            "src/my_agent/app_module.py",
            "src/my_agent/agents/__init__.py",
            "src/my_agent/agents/support.py",
            "evals/__init__.py",
            "evals/support_eval.py",
            "evals/datasets/support.jsonl",
            "tests/__init__.py",
            "tests/test_support.py",
        ]
        for relative in expected:
            assert (generated / relative).is_file(), f"missing: {relative}"


class TestPyprojectContent:
    """``pyproject.toml`` reflects the wizard answers + spec contract."""

    def test_declares_ajolopy_dependency(self, generated: Path) -> None:
        text = (generated / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "my-agent"' in text
        assert "ajolopy>=0.1.0" in text
        assert 'packages = ["src/my_agent"]' in text


class TestMainPy:
    """``main.py`` references the package's ``app_module``."""

    def test_main_references_app_module(self, generated: Path) -> None:
        text = (generated / "src" / "my_agent" / "main.py").read_text(encoding="utf-8")
        assert "from my_agent.app_module import AppModule" in text
        assert "AjolopyFactory.create(AppModule)" in text


class TestSupportAgent:
    """``agents/support.py`` carries the chosen LLM model + class prefix."""

    def test_default_agent_uses_claude_sonnet(self, generated: Path) -> None:
        text = (generated / "src" / "my_agent" / "agents" / "support.py").read_text(
            encoding="utf-8"
        )
        assert "claude-sonnet-4-7" in text
        assert "@Agent" in text
        assert "@Tool" in text
        assert "class Support" in text


class TestEnvExample:
    """``.env.example`` lists the chosen provider's env var."""

    def test_anthropic_env_var(self, generated: Path) -> None:
        text = (generated / ".env.example").read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY=" in text
        assert "APP_ENV=development" in text


class TestDatasetSeed:
    """The sample JSONL ships with three cases."""

    def test_dataset_has_three_lines(self, generated: Path) -> None:
        text = (
            (generated / "evals" / "datasets" / "support.jsonl").read_text(encoding="utf-8").strip()
        )
        lines = text.splitlines()
        assert len(lines) == 3


class TestDockerfile:
    """The Dockerfile is present and referenced the package's ASGI target."""

    def test_dockerfile_references_package_main(self, generated: Path) -> None:
        text = (generated / "Dockerfile").read_text(encoding="utf-8")
        assert "my_agent.main:app" in text


class TestGenerationLog:
    """The per-file ``✓`` block is printed for each written file."""

    def test_log_contains_check_marks(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes"])
        assert result.exit_code == new_cmd.EXIT_OK
        assert "Creating my-agent/..." in result.stdout
        for relative in [
            "pyproject.toml",
            "README.md",
            ".env.example",
            ".gitignore",
            "Dockerfile",
            "src/my_agent/main.py",
            "evals/support_eval.py",
        ]:
            assert f"✓ {relative}" in result.stdout, f"missing log line for {relative}"


class TestReadmeContent:
    """README lists the next-step commands documented in the spec."""

    def test_readme_lists_next_steps(self, generated: Path) -> None:
        text = (generated / "README.md").read_text(encoding="utf-8")
        assert "uv sync" in text
        assert "ajolopy dev" in text
        assert "ajolopy eval" in text
