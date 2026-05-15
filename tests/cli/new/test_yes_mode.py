"""``--yes`` non-interactive path: defaults + flag overrides."""

from pathlib import Path

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new


class TestYesDefaults:
    """``ajolopy new my-agent --yes`` uses every default answer."""

    def test_yes_uses_documented_defaults(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr

        env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" in env_text  # default LLM = anthropic

        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert "@Agent" in support_py  # default feature = agent

        # Docker + eval default ON.
        assert (tmp_cwd / "my-agent" / "Dockerfile").is_file()
        assert (tmp_cwd / "my-agent" / "evals" / "support_eval.py").is_file()


class TestYesWithOverrides:
    """``--yes`` accepts the documented overrides."""

    def test_yes_with_overrides_short_circuits_prompts(self, tmp_cwd: Path) -> None:
        result = invoke_new(
            [
                "my-agent",
                "--yes",
                "--llm",
                "openai",
                "--feature",
                "workflow",
                "--no-docker",
                "--no-eval",
            ]
        )
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr

        env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in env_text

        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert "@Workflow" in support_py

        assert not (tmp_cwd / "my-agent" / "Dockerfile").exists()
        assert not (tmp_cwd / "my-agent" / "evals").exists()


class TestYesNoPromptIO:
    """``--yes`` never calls ``builtins.input`` -- a poisoned ``input`` proves it."""

    def test_yes_does_not_call_input(self, tmp_cwd: Path) -> None:
        import builtins

        original = builtins.input

        def _poisoned(_prompt: object = "") -> str:
            raise AssertionError("--yes must not call builtins.input")

        builtins.input = _poisoned
        try:
            result = invoke_new(["my-agent", "--yes"])
        finally:
            builtins.input = original

        assert result.exit_code == new_cmd.EXIT_OK
