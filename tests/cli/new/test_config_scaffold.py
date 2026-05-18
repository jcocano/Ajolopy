"""Scaffold emits a ``BaseConfig`` subclass + wires it into ``AppModule``.

Regression coverage for AJ-94. Pre-fix, the scaffold's ``.env.example``
included ``ANTHROPIC_API_KEY`` / ``APP_ENV`` / ``LOG_LEVEL`` (or the
matching provider variant), but no project-level ``BaseConfig`` subclass
was emitted. Two CLI commands broke on every fresh install:

- ``ajolopy doctor`` reported ``env_validation FAIL`` because the
  framework's bare ``BaseConfig`` is ``extra="forbid"``.
- ``ajolopy env:show`` / ``env:validate`` errored with
  ``"no BaseConfig subclass found in '<pkg>.app_module'"`` — the
  commands were 100% unusable.

The fix emits ``src/<pkg>/config.py`` with an ``AppConfig`` subclass
declaring one field per ``.env.example`` key, then registers it via
``providers=[AppConfig]`` on the root ``AppModule`` so the env
discovery path (see ``ajolopy.cli.commands.env._discover_config``)
locates it. This module asserts every leg of that contract per
provider variant the wizard supports.
"""

from pathlib import Path

import pytest

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new

# ---------------------------------------------------------------------------
# Per-provider field expectations.
#
# For the three single-provider choices the env var name lives in
# ``_PROVIDER_DEFAULTS``; for ``--llm universal`` the env var depends on
# the chosen prefix (``OLLAMA_BASE_URL`` for the no-API-key local
# default, ``${PREFIX}_API_KEY`` for every cloud upstream).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("llm", "expected_env_var"),
    [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GOOGLE_API_KEY"),
        ("universal", "OLLAMA_BASE_URL"),
    ],
)
def test_config_py_exists_and_declares_provider_field(
    tmp_cwd: Path,
    llm: str,
    expected_env_var: str,
) -> None:
    """``src/<pkg>/config.py`` ships an ``AppConfig`` with the provider's env field."""
    result = invoke_new(["my-agent", "--yes", "--llm", llm, "--no-docker", "--no-eval"])
    assert result.exit_code == new_cmd.EXIT_OK, result.stderr

    config_py = tmp_cwd / "my-agent" / "src" / "my_agent" / "config.py"
    assert config_py.is_file(), "scaffold must emit src/<pkg>/config.py"

    text = config_py.read_text(encoding="utf-8")
    # Imports the framework BaseConfig — required for the env:* discovery
    # path that walks ``app_module`` looking for BaseConfig subclasses.
    assert "from ajolopy.config import BaseConfig" in text
    # Declares the canonical ``AppConfig`` class name; the env:*
    # discovery accepts any BaseConfig subclass, but the docs anchor to
    # ``AppConfig`` so the scaffold sticks to one name.
    assert "class AppConfig(BaseConfig):" in text
    # Carries the provider's env var as a typed field — verifies the
    # _PROVIDER_DEFAULTS -> _app_config_fields plumbing per choice.
    assert f'{expected_env_var}: str = ""' in text


class TestUniversalPrefixFieldRouting:
    """``--llm universal --universal-prefix <p>`` routes the AppConfig field."""

    @pytest.mark.parametrize(
        ("prefix", "expected_env_var"),
        [
            ("groq", "GROQ_API_KEY"),
            ("together", "TOGETHER_API_KEY"),
            ("mistral", "MISTRAL_API_KEY"),
            ("deepseek", "DEEPSEEK_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
        ],
    )
    def test_cloud_prefixes_declare_api_key_field(
        self,
        tmp_cwd: Path,
        prefix: str,
        expected_env_var: str,
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
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "config.py").read_text(encoding="utf-8")
        assert f'{expected_env_var}: str = ""' in text

    def test_ollama_default_declares_base_url_field_not_api_key(
        self,
        tmp_cwd: Path,
    ) -> None:
        result = invoke_new(["my-agent", "--yes", "--llm", "universal", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "config.py").read_text(encoding="utf-8")
        # The universal:ollama default routes through OLLAMA_BASE_URL —
        # no API key field should leak in.
        assert 'OLLAMA_BASE_URL: str = ""' in text
        assert "API_KEY" not in text


class TestAlwaysOnFields:
    """Every variant ships the documented ``APP_ENV`` + ``LOG_LEVEL`` fields."""

    @pytest.mark.parametrize("llm", ["anthropic", "openai", "gemini", "universal"])
    def test_app_env_and_log_level_always_declared(
        self,
        tmp_cwd: Path,
        llm: str,
    ) -> None:
        result = invoke_new(["my-agent", "--yes", "--llm", llm, "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "config.py").read_text(encoding="utf-8")
        assert 'APP_ENV: str = "development"' in text
        assert 'LOG_LEVEL: str = "debug"' in text


class TestMcpFeatureAddsGitHubField:
    """``--feature mcp`` declares ``GITHUB_PERSONAL_ACCESS_TOKEN`` on AppConfig.

    Mirrors the commented-out ``# GITHUB_PERSONAL_ACCESS_TOKEN=`` line
    the mcp ``.env.example`` already ships — declaring the field here
    means a user who uncomments + pastes a token in ``.env`` no longer
    trips ``BaseConfig``'s ``extra_forbidden`` check.
    """

    def test_mcp_feature_declares_github_token_field(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--feature", "mcp", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "config.py").read_text(encoding="utf-8")
        assert 'GITHUB_PERSONAL_ACCESS_TOKEN: str = ""' in text

    def test_agent_feature_does_not_declare_github_token_field(
        self,
        tmp_cwd: Path,
    ) -> None:
        result = invoke_new(["my-agent", "--yes", "--feature", "agent", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "config.py").read_text(encoding="utf-8")
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in text


class TestAppModuleWiring:
    """``app_module.py`` imports + registers ``AppConfig`` via ``providers=``."""

    def test_app_module_imports_app_config(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "app_module.py").read_text(
            encoding="utf-8"
        )
        assert "from my_agent.config import AppConfig" in text

    def test_app_module_registers_app_config_as_provider(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "src" / "my_agent" / "app_module.py").read_text(
            encoding="utf-8"
        )
        # The env:* discovery walks ``app_module`` for the first
        # BaseConfig subclass. Registering AppConfig via ``providers=``
        # binds it to the module so the DI container resolves it AND
        # the env:* commands locate it.
        assert "providers=[AppConfig]" in text


class TestConfigDiscoverableByEnvCommands:
    """The emitted config is reachable through the env:* discovery path.

    Runs the generated project in a subprocess so the @Agent decorator
    in the scaffold's ``support.py`` can register its provider without
    contaminating the pytest interpreter's provider registry. Mirrors
    the pattern ``test_smoke_import.py`` uses for the same reason.
    """

    def test_env_show_discovers_app_config_in_generated_project(
        self,
        tmp_cwd: Path,
    ) -> None:
        import os
        import subprocess
        import sys

        # Generate the project with the default --llm anthropic so the
        # subprocess can verify the ``ANTHROPIC_API_KEY`` field surfaces
        # in the env:show table. ``test_smoke_import.py`` already proves
        # the package imports cleanly under the same env vars.
        result = invoke_new(["my-agent", "--yes", "--no-docker", "--no-eval"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        project = tmp_cwd / "my-agent"
        src_dir = project / "src"

        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = "test-dummy"
        # Prepend the generated ``src/`` so the env:show discovery walk
        # imports ``my_agent.app_module`` from the right tree.
        env["PYTHONPATH"] = os.pathsep.join([str(src_dir), env.get("PYTHONPATH", "")]).strip(
            os.pathsep
        )

        # The dispatcher's env-show entry takes its cwd from
        # ``Path.cwd()``; pass ``cwd=project`` so the subprocess
        # discovery walks the generated tree. Drive the CLI through
        # a one-liner that imports ``ajolopy.cli`` (which exposes
        # ``main``) so the test stays independent of the install path
        # of the ``ajolopy`` console script.
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from ajolopy.cli import main; sys.exit(main(['env:show']))",
            ],
            env=env,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, (
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )
        out = completed.stdout
        # Every declared field appears in the rendered table — proves the
        # discovery walk + introspection both work end-to-end against a
        # fresh-scaffold project.
        assert "ANTHROPIC_API_KEY" in out
        assert "APP_ENV" in out
        assert "LOG_LEVEL" in out
