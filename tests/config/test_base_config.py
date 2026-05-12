"""Tests for BaseConfig — required/optional, .env loading, precedence.

Covers the "BaseConfig — required vs optional" and "Test-environment file"
acceptance groups in specs/config-service.md.
"""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ajolopy.config import BaseConfig

if TYPE_CHECKING:
    from pathlib import Path


class _RequiredOnly(BaseConfig):
    APP_NAME: str


class _OptionalDefault(BaseConfig):
    APP_NAME: str = "fallback"


class _Mixed(BaseConfig):
    APP_NAME: str
    APP_ENV: str = "development"
    APP_PORT: int = 3000


def test_missing_required_field_raises_with_field_name() -> None:
    with pytest.raises(ValidationError) as info:
        # reportCallIssue: deliberately not providing APP_NAME — that's the test.
        _RequiredOnly()  # pyright: ignore[reportCallIssue]
    assert "APP_NAME" in str(info.value)


def test_optional_field_uses_declared_default_when_env_unset() -> None:
    config = _OptionalDefault()
    assert config.APP_NAME == "fallback"


def test_dotenv_values_load_when_process_env_unset(
    env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_NAME", raising=False)
    (env_dir / ".env").write_text("APP_NAME=from-dotenv\n", encoding="utf-8")
    # reportCallIssue: APP_NAME is supplied via the dotenv source at runtime.
    config = _RequiredOnly()  # pyright: ignore[reportCallIssue]
    assert config.APP_NAME == "from-dotenv"


def test_process_env_takes_precedence_over_dotenv(
    env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (env_dir / ".env").write_text("APP_NAME=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "from-process")
    # reportCallIssue: APP_NAME is supplied via the process env at runtime.
    config = _RequiredOnly()  # pyright: ignore[reportCallIssue]
    assert config.APP_NAME == "from-process"


def test_extra_unknown_field_in_dotenv_raises(
    env_dir: Path,
) -> None:
    (env_dir / ".env").write_text(
        "APP_NAME=hello\nMISSPELLED_VAR=oops\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as info:
        # reportCallIssue: APP_NAME is supplied via the dotenv source at runtime.
        _Mixed()  # pyright: ignore[reportCallIssue]
    assert "MISSPELLED_VAR" in str(info.value)


def test_mixed_required_and_optional_uses_defaults_where_unset(
    env_dir: Path,
) -> None:
    (env_dir / ".env").write_text("APP_NAME=hello\n", encoding="utf-8")
    # reportCallIssue: APP_NAME is supplied via the dotenv source at runtime.
    config = _Mixed()  # pyright: ignore[reportCallIssue]
    assert config.APP_NAME == "hello"
    assert config.APP_ENV == "development"
    assert config.APP_PORT == 3000
