"""``--llm universal`` scaffold: prefix routing + env-doc + flag overrides.

The universal provider routes by a ``"<prefix>:<model>"`` model string
(see :class:`ajolopy.providers.universal_openai.UniversalOpenAIProvider`).
The wizard's job is to:

1. Default to ``ollama:llama3.3`` so a zero-config local run works.
2. Honour ``--universal-prefix`` so the user can target Groq / Together
   / Mistral / DeepSeek / OpenRouter without editing the generated
   ``support.py`` by hand.
3. Document the per-prefix env vars (API key for cloud upstreams,
   ``OLLAMA_BASE_URL`` escape hatch for the local case) in the
   generated ``.env.example``.

This module exists separately from ``test_provider_variants.py`` because
universal is the only choice that adds a second axis (the prefix) to the
generated tree.
"""

from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new


class TestUniversalDefaults:
    """``--llm universal`` with no extra flags scaffolds ``ollama:llama3.3``."""

    def test_default_model_string_is_ollama(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--llm", "universal", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr

        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        # The agent decorator gets the universal-provider model contract
        # baked in, not a bare model id.
        assert 'model="ollama:llama3.3"' in support_py

    def test_default_env_example_documents_ollama_base_url(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--llm", "universal", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr

        env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
        # Header line emitted by the base template + the universal env
        # doc appended via ``extra_env_lines``.
        assert "OLLAMA_BASE_URL" in env_text
        # No API-key env var leaks in for the Ollama default — universal
        # over Ollama is the no-account path.
        assert "ANTHROPIC_API_KEY" not in env_text
        assert "OPENAI_API_KEY" not in env_text


class TestUniversalPrefixOverride:
    """``--universal-prefix <name>`` swaps both the model and the env var."""

    @pytest.mark.parametrize(
        ("prefix", "expected_model", "expected_env"),
        [
            ("groq", "groq:llama-3.3-70b-versatile", "GROQ_API_KEY"),
            (
                "together",
                "together:meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "TOGETHER_API_KEY",
            ),
            ("mistral", "mistral:mistral-large-latest", "MISTRAL_API_KEY"),
            ("deepseek", "deepseek:deepseek-chat", "DEEPSEEK_API_KEY"),
            (
                "openrouter",
                "openrouter:meta-llama/llama-3.3-70b-instruct",
                "OPENROUTER_API_KEY",
            ),
        ],
    )
    def test_prefix_routes_model_and_env_var(
        self,
        tmp_cwd: Path,
        prefix: str,
        expected_model: str,
        expected_env: str,
    ) -> None:
        result = invoke_new(
            [
                "my-agent",
                "--yes",
                "--llm",
                "universal",
                "--universal-prefix",
                prefix,
                "--no-docker",
                "--no-eval",
            ]
        )
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr

        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert f'model="{expected_model}"' in support_py

        env_text = (tmp_cwd / "my-agent" / ".env.example").read_text(encoding="utf-8")
        assert f"{expected_env}=" in env_text
        # The base-URL escape hatch documented for every cloud prefix.
        assert f"{prefix.upper()}_BASE_URL" in env_text


class TestUniversalModelOverride:
    """``--universal-model <name>`` overrides the per-prefix default model."""

    def test_custom_model_for_ollama(self, tmp_cwd: Path) -> None:
        result = invoke_new(
            [
                "my-agent",
                "--yes",
                "--llm",
                "universal",
                "--universal-prefix",
                "ollama",
                "--universal-model",
                "qwen2.5:32b",
                "--no-docker",
                "--no-eval",
            ]
        )
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert 'model="ollama:qwen2.5:32b"' in support_py

    def test_custom_model_for_groq(self, tmp_cwd: Path) -> None:
        result = invoke_new(
            [
                "my-agent",
                "--yes",
                "--llm",
                "universal",
                "--universal-prefix",
                "groq",
                "--universal-model",
                "mixtral-8x7b-32768",
                "--no-docker",
                "--no-eval",
            ]
        )
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        support_py = (
            tmp_cwd / "my-agent" / "src" / "my_agent" / "agents" / "support.py"
        ).read_text(encoding="utf-8")
        assert 'model="groq:mixtral-8x7b-32768"' in support_py


class TestUniversalArgparseSurface:
    """The wizard's argparse choices include 'universal' (regression of AJ-81)."""

    def test_universal_is_an_accepted_llm_choice(self) -> None:
        # The bug was that ``--llm universal`` errored with
        # ``invalid choice: 'universal' (choose from anthropic, openai, gemini)``.
        # The fix promotes universal to a first-class choice; the
        # argparse layer is the source of truth here.
        assert "universal" in new_cmd._VALID_LLM

    def test_universal_prefix_choices_match_provider_table(self) -> None:
        # The valid-prefix tuple should mirror the spec's v0.1 table —
        # adding a new prefix to the provider without adding it here
        # would silently break the wizard.
        expected = {"ollama", "groq", "together", "mistral", "deepseek", "openrouter"}
        assert set(new_cmd._VALID_UNIVERSAL_PREFIX) == expected


class TestUniversalNextStepsMessage:
    """The CLI's final tip surfaces the prefix-specific env var."""

    def test_next_steps_mentions_ollama_base_url_by_default(self, tmp_cwd: Path) -> None:
        _ = tmp_cwd
        result = invoke_new(["my-agent", "--yes", "--llm", "universal", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        assert "OLLAMA_BASE_URL" in result.stdout

    def test_next_steps_mentions_api_key_for_cloud_prefix(self, tmp_cwd: Path) -> None:
        _ = tmp_cwd
        result = invoke_new(
            [
                "my-agent",
                "--yes",
                "--llm",
                "universal",
                "--universal-prefix",
                "groq",
                "--no-docker",
                "--no-eval",
            ]
        )
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        assert "GROQ_API_KEY" in result.stdout
