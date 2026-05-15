"""``ajolopy env:show`` — list every declared env var with set/missing state.

Each acceptance criterion gets a dedicated test class so a regression
points at the failing branch immediately.
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import env as env_cmd
from ajolopy.cli.dispatcher import build_parser

from .conftest import SAMPLE_CONFIG


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environ: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Drive ``_command_show`` against StringIO buffers."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = env_cmd._command_show(
        args,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        environ=environ if environ is not None else {},
    )
    return code, stdout.getvalue(), stderr.getvalue()


class TestListsEveryField:
    def test_renders_every_field_declared_on_basecconfig(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        code, out, _err = _run(["env-show"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "APP_ENV", "LOG_LEVEL"):
            assert name in out


class TestSetVsMissingGlyph:
    def test_set_marker_when_env_var_present(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        environ = {"APP_ENV": "production"}
        code, out, _err = _run(["env-show"], cwd=tmp_path, environ=environ)
        assert code == env_cmd.EXIT_OK
        # Non-TTY (StringIO) renders the ASCII fallback.
        assert "APP_ENV" in out
        assert "[set]" in out
        assert "production" in out

    def test_missing_marker_when_env_var_absent(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        code, out, _err = _run(["env-show"], cwd=tmp_path, environ={})
        assert code == env_cmd.EXIT_OK
        assert "[missing]" in out
        assert "ANTHROPIC_API_KEY" in out


class TestMaskingSecretLookingNames:
    def test_api_key_value_is_masked_in_text_output(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="secretapp", config_body=SAMPLE_CONFIG)
        environ = {"ANTHROPIC_API_KEY": "sk-abcdefghijklmnopqrstuvwxyz1234"}
        code, out, _err = _run(["env-show"], cwd=tmp_path, environ=environ)
        assert code == env_cmd.EXIT_OK
        # The raw secret never appears.
        assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in out
        # Only the first 3 + last 4 + length are shown.
        assert "sk-" in out
        assert "1234" in out
        assert "chars" in out

    def test_non_secret_value_is_rendered_verbatim(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        environ = {"APP_ENV": "production"}
        code, out, _err = _run(["env-show"], cwd=tmp_path, environ=environ)
        assert code == env_cmd.EXIT_OK
        assert "production" in out

    def test_short_secret_collapses_to_length_only(self) -> None:
        masked = env_cmd._mask_value("short")
        assert "short" not in masked
        assert "chars" in masked

    def test_long_secret_keeps_first3_last4(self) -> None:
        masked = env_cmd._mask_value("ABCDEFGHIJKLMNOP")
        assert masked.startswith("ABC")
        assert "MNOP" in masked
        assert "16 chars" in masked

    @pytest.mark.parametrize(
        "name",
        [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "SLACK_TOKEN",
            "DB_PASSWORD",
            "STRIPE_SECRET",
            "some_secret_value",
            "lowercase_key",
        ],
    )
    def test_secret_pattern_matches_documented_substrings(self, name: str) -> None:
        assert env_cmd._looks_secret(name) is True

    @pytest.mark.parametrize(
        "name",
        ["APP_ENV", "LOG_LEVEL", "PORT", "HOSTNAME"],
    )
    def test_non_secret_pattern_does_not_match(self, name: str) -> None:
        assert env_cmd._looks_secret(name) is False


class TestCIJSONOutput:
    def test_ci_payload_shape(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        environ = {
            "ANTHROPIC_API_KEY": "sk-abcdefghijklmnopqrstuvwxyz1234",
            "APP_ENV": "production",
        }
        code, out, _err = _run(["env-show", "--ci"], cwd=tmp_path, environ=environ)
        assert code == env_cmd.EXIT_OK
        payload = json.loads(out)
        assert payload["schema_version"] == env_cmd.SCHEMA_VERSION
        assert payload["subcommand"] == "env:show"
        assert payload["exit_code"] == env_cmd.EXIT_OK
        by_name = {entry["name"]: entry for entry in payload["vars"]}
        # Every field appears, in declared order.
        names = [entry["name"] for entry in payload["vars"]]
        assert names == [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "APP_ENV",
            "LOG_LEVEL",
        ]
        # Secret-looking names are masked.
        anthropic = by_name["ANTHROPIC_API_KEY"]
        assert anthropic["set"] is True
        assert anthropic["secret"] is True
        assert anthropic["length"] == len("sk-abcdefghijklmnopqrstuvwxyz1234")
        assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in anthropic["masked_value"]
        # Missing values are reported with length 0 + null masked_value.
        openai = by_name["OPENAI_API_KEY"]
        assert openai["set"] is False
        assert openai["length"] == 0
        assert openai["masked_value"] is None


class TestDiscoveryFailures:
    def test_no_src_directory_returns_discovery_exit_code(
        self,
        tmp_path: Path,
    ) -> None:
        code, _out, err = _run(["env-show"], cwd=tmp_path)
        assert code == env_cmd.EXIT_DISCOVERY
        assert "no 'src/'" in err

    def test_multiple_packages_under_src_returns_discovery_exit_code(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(
            tmp_path,
            package="envapp",
            config_body=SAMPLE_CONFIG,
            extra_packages=("altpkg",),
        )
        code, _out, err = _run(["env-show"], cwd=tmp_path)
        assert code == env_cmd.EXIT_DISCOVERY
        assert "multiple packages" in err

    def test_no_baseconfig_subclass_returns_discovery_exit_code(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(
            tmp_path,
            package="envapp",
            config_body="# no config here\n",
        )
        code, _out, err = _run(["env-show"], cwd=tmp_path)
        assert code == env_cmd.EXIT_DISCOVERY
        assert "no BaseConfig" in err

    def test_fallback_discovery_finds_config_in_package_init(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(
            tmp_path,
            package="fallbackapp",
            config_body=SAMPLE_CONFIG,
            in_app_module=False,
        )
        code, out, _err = _run(["env-show"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        assert "ANTHROPIC_API_KEY" in out


class TestEmptyConfig:
    def test_empty_config_renders_no_fields_message(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        body = """
        from ajolopy.config import BaseConfig


        class EmptyConfig(BaseConfig):
            pass
        """
        project_factory(tmp_path, package="envapp", config_body=body)
        code, out, _err = _run(["env-show"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        assert "no fields" in out


class TestDotenvFileIsRead:
    def test_dotenv_value_appears_as_set(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        # Values declared in ``.env`` (but absent from ``os.environ``)
        # are still shown as set — matching what ``BaseConfig()``
        # would actually load at boot.
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        (tmp_path / ".env").write_text(
            "ANTHROPIC_API_KEY=sk-from-dotenv\nAPP_ENV=staging\n",
            encoding="utf-8",
        )
        code, out, _err = _run(["env-show"], cwd=tmp_path, environ={})
        assert code == env_cmd.EXIT_OK
        assert "[set]" in out
        assert "staging" in out
        # Secret values from .env are still masked.
        assert "sk-from-dotenv" not in out

    def test_os_environ_wins_over_dotenv(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        (tmp_path / ".env").write_text("APP_ENV=staging\n", encoding="utf-8")
        code, out, _err = _run(
            ["env-show"],
            cwd=tmp_path,
            environ={"APP_ENV": "production"},
        )
        assert code == env_cmd.EXIT_OK
        # The process-env value shadows the dotenv value.
        assert "production" in out
        assert "staging" not in out
