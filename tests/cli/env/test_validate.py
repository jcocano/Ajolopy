"""``ajolopy env:validate`` — instantiate BaseConfig + report per-field results."""

import io
import json
import os
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
) -> tuple[int, str, str]:
    """Drive ``_command_validate`` against StringIO buffers."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = env_cmd._command_validate(
        args,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
    )
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every variable used by the sample config so the test owns state."""
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "APP_ENV", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir into ``tmp_path`` so the implicit ``.env`` lookup hits the fixture."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestAllValidExitsZero:
    def test_every_field_satisfied_returns_exit_ok(
        self,
        tmp_path: Path,
        project_factory: Any,
        isolated_env: None,
        in_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_factory(tmp_path, package="validateapp", config_body=SAMPLE_CONFIG)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        code, out, _err = _run(["env-validate"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        assert "valid" in out
        assert "ANTHROPIC_API_KEY" in out
        assert "4 valid, 0 invalid" in out


class TestInvalidExitsOne:
    def test_missing_required_field_returns_exit_failed(
        self,
        tmp_path: Path,
        project_factory: Any,
        isolated_env: None,
        in_tmp: Path,
    ) -> None:
        project_factory(tmp_path, package="invalidapp", config_body=SAMPLE_CONFIG)
        # ANTHROPIC_API_KEY is required and intentionally unset.
        code, _out, _err = _run(["env-validate"], cwd=tmp_path)
        assert code == env_cmd.EXIT_FAILED

    def test_invalid_marker_only_for_failing_fields(
        self,
        tmp_path: Path,
        project_factory: Any,
        isolated_env: None,
        in_tmp: Path,
    ) -> None:
        project_factory(tmp_path, package="invalidapp", config_body=SAMPLE_CONFIG)
        code, out, _err = _run(["env-validate"], cwd=tmp_path)
        assert code == env_cmd.EXIT_FAILED
        # The optional / defaulted fields are still listed as valid.
        for name in ("OPENAI_API_KEY", "APP_ENV", "LOG_LEVEL"):
            assert name in out
        # Summary reflects the split.
        assert "3 valid, 1 invalid" in out


class TestPerFieldErrorMessage:
    def test_error_message_attached_to_field(
        self,
        tmp_path: Path,
        project_factory: Any,
        isolated_env: None,
        in_tmp: Path,
    ) -> None:
        body = """
        from ajolopy.config import BaseConfig
        from pydantic import Field


        class StrictConfig(BaseConfig):
            PORT: int = Field(default=0, ge=1, le=65535)
        """
        project_factory(tmp_path, package="invalidapp", config_body=body)
        os.environ["PORT"] = "70000"  # out of range; cleaned up below.
        try:
            code, out, _err = _run(["env-validate"], cwd=tmp_path)
        finally:
            os.environ.pop("PORT", None)
        assert code == env_cmd.EXIT_FAILED
        assert "PORT" in out
        # Pydantic surfaces a human-readable ``msg`` on each error entry;
        # we accept any non-empty message here so the test doesn't break
        # on a pydantic minor-version copy edit.
        assert "[fail]" in out


class TestCIJSONOutput:
    def test_ci_payload_when_all_valid(
        self,
        tmp_path: Path,
        project_factory: Any,
        isolated_env: None,
        in_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_factory(tmp_path, package="validateapp", config_body=SAMPLE_CONFIG)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        code, out, _err = _run(["env-validate", "--ci"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        payload = json.loads(out)
        assert payload["schema_version"] == env_cmd.SCHEMA_VERSION
        assert payload["subcommand"] == "env:validate"
        assert payload["exit_code"] == env_cmd.EXIT_OK
        assert payload["errors"] == []
        assert set(payload["valid"]) == {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "APP_ENV",
            "LOG_LEVEL",
        }

    def test_ci_payload_includes_per_field_error_entry(
        self,
        tmp_path: Path,
        project_factory: Any,
        isolated_env: None,
        in_tmp: Path,
    ) -> None:
        project_factory(tmp_path, package="invalidapp", config_body=SAMPLE_CONFIG)
        code, out, _err = _run(["env-validate", "--ci"], cwd=tmp_path)
        assert code == env_cmd.EXIT_FAILED
        payload = json.loads(out)
        assert payload["subcommand"] == "env:validate"
        assert payload["exit_code"] == env_cmd.EXIT_FAILED
        fields = [entry["field"] for entry in payload["errors"]]
        assert "ANTHROPIC_API_KEY" in fields
        # Every error entry carries a message.
        for entry in payload["errors"]:
            assert entry["message"]


class TestDiscoveryFailure:
    def test_no_baseconfig_returns_discovery_exit(
        self,
        tmp_path: Path,
        project_factory: Any,
    ) -> None:
        project_factory(
            tmp_path,
            package="validateapp",
            config_body="# nothing\n",
        )
        code, _out, err = _run(["env-validate"], cwd=tmp_path)
        assert code == env_cmd.EXIT_DISCOVERY
        assert "no BaseConfig" in err
