"""Provider variants: model name + env var swap per ``--llm`` choice."""

from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new


@pytest.mark.parametrize(
    ("llm", "model", "env_var"),
    [
        ("anthropic", "claude-opus-4-7", "ANTHROPIC_API_KEY"),
        ("openai", "gpt-4o", "OPENAI_API_KEY"),
        ("gemini", "gemini-2.0-flash-exp", "GOOGLE_API_KEY"),
    ],
)
def test_provider_model_and_env_var_match_spec(
    tmp_cwd: Path,
    llm: str,
    model: str,
    env_var: str,
) -> None:
    """Each provider produces the documented model + env-var pair."""
    result = invoke_new(["my-agent", "--yes", "--llm", llm, "--no-docker", "--no-eval"])
    assert result.exit_code == new_cmd.EXIT_OK, result.stderr

    support_py = (tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py").read_text(
        encoding="utf-8"
    )
    assert f'model="{model}"' in support_py

    env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
    assert f"{env_var}=" in env_text


def test_next_steps_block_mentions_provider_env_var(tmp_cwd: Path) -> None:
    """The CLI's final tip names the env var the user must fill in."""
    result = invoke_new(["my-agent", "--yes", "--llm", "gemini"])
    assert result.exit_code == new_cmd.EXIT_OK, result.stderr
    assert "GOOGLE_API_KEY" in result.stdout
