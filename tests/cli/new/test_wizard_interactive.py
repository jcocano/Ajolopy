"""Interactive wizard path: four prompts answered through ``builtins.input``."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new


def _scripted_input(answers: list[str]) -> Callable[..., str]:
    """Return a fake ``builtins.input`` that consumes ``answers`` in order."""
    iterator: Iterator[str] = iter(answers)

    def _fake_input(_prompt: object = "") -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AssertionError("wizard asked for more answers than the test provided") from exc

    return _fake_input


class TestPromptOrder:
    """Each of the four wizard questions is asked once, in the documented order."""

    def test_full_interactive_happy_path(
        self,
        tmp_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ``llm=openai``, ``feature=workflow``, ``docker=n``, ``eval=y``.
        monkeypatch.setattr(
            "builtins.input",
            _scripted_input(["openai", "workflow", "n", "y"]),
        )
        result = invoke_new(["my-agent"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr

        env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in env_text

        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert "@Workflow" in support_py

        # ``--no-docker`` was selected via the prompt.
        assert not (tmp_cwd / "my-agent" / "Dockerfile").exists()
        # ``--no-eval`` was NOT selected.
        assert (tmp_cwd / "my-agent" / "evals" / "support_eval.py").is_file()


class TestPromptDefaults:
    """Empty answers fall back to the first choice in the vocabulary."""

    def test_empty_answers_use_first_choice(
        self,
        tmp_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("builtins.input", _scripted_input(["", "", "", ""]))
        result = invoke_new(["my-agent"])
        assert result.exit_code == new_cmd.EXIT_OK
        # Default LLM is the first valid choice -> anthropic.
        env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" in env_text
        # Default feature -> agent.
        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert "@Agent" in support_py
        # Default Y/N answers are yes for both Dockerfile and eval.
        assert (tmp_cwd / "my-agent" / "Dockerfile").is_file()
        assert (tmp_cwd / "my-agent" / "evals" / "support_eval.py").is_file()


class TestRetryLoop:
    """Invalid prompt answers re-prompt up to 3 times before aborting."""

    def test_invalid_then_valid_recovers(
        self,
        tmp_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "builtins.input",
            _scripted_input(["bogus", "anthropic", "agent", "y", "y"]),
        )
        result = invoke_new(["my-agent"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        # The invalid attempt produces a stderr diagnostic.
        assert "invalid" in result.stderr.lower()

    def test_three_invalid_in_a_row_aborts(
        self,
        tmp_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "builtins.input",
            _scripted_input(["bogus", "still-bogus", "nope-bogus"]),
        )
        result = invoke_new(["my-agent"])
        assert result.exit_code == new_cmd.EXIT_USAGE
        assert "too many invalid answers" in result.stderr.lower()
        assert not (tmp_cwd / "my-agent").exists()


class TestKeyboardInterrupt:
    """Ctrl+C mid-wizard exits 130 per shell convention."""

    def test_keyboard_interrupt_exits_one_thirty(
        self,
        tmp_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise_kbd(_prompt: object = "") -> str:
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _raise_kbd)
        result = invoke_new(["my-agent"])
        assert result.exit_code == new_cmd.EXIT_INTERRUPTED
        assert "aborted" in result.stderr.lower()
        assert not (tmp_cwd / "my-agent").exists()
