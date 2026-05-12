"""Tests for the .env.test layering rule.

Covers the "Test-environment file" acceptance group: when APP_ENV=test, the
.env.test file is loaded *after* .env so its values override the base file.
For any other APP_ENV, .env.test is ignored even if present.
"""

from typing import TYPE_CHECKING

from ajolopy.config import BaseConfig

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _Config(BaseConfig):
    APP_NAME: str


def test_env_test_overrides_env_when_app_env_is_test(
    env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (env_dir / ".env").write_text("APP_NAME=base-value\n", encoding="utf-8")
    (env_dir / ".env.test").write_text("APP_NAME=test-value\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "test")
    # reportCallIssue: APP_NAME is supplied via the dotenv source at runtime.
    config = _Config()  # pyright: ignore[reportCallIssue]
    assert config.APP_NAME == "test-value"


def test_env_test_ignored_when_app_env_is_not_test(
    env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (env_dir / ".env").write_text("APP_NAME=base-value\n", encoding="utf-8")
    (env_dir / ".env.test").write_text("APP_NAME=test-value\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")
    # reportCallIssue: APP_NAME is supplied via the dotenv source at runtime.
    config = _Config()  # pyright: ignore[reportCallIssue]
    assert config.APP_NAME == "base-value"


def test_env_test_ignored_when_app_env_unset(
    env_dir: Path,
) -> None:
    (env_dir / ".env").write_text("APP_NAME=base-value\n", encoding="utf-8")
    (env_dir / ".env.test").write_text("APP_NAME=test-value\n", encoding="utf-8")
    # reportCallIssue: APP_NAME is supplied via the dotenv source at runtime.
    config = _Config()  # pyright: ignore[reportCallIssue]
    assert config.APP_NAME == "base-value"
