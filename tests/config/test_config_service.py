"""Tests for ConfigService — method surface and APP_ENV predicates.

Covers the "ConfigService method surface" and "Negative cases" acceptance
groups in specs/config-service.md.
"""

from typing import TYPE_CHECKING

import pytest

from ajolopy.config import BaseConfig, ConfigMissingError, ConfigService

if TYPE_CHECKING:
    from pathlib import Path


class _AppConfig(BaseConfig):
    APP_NAME: str = "ajolopy"
    APP_ENV: str = "development"
    APP_PORT: str = "3000"  # str so get_int's coercion path is exercised end-to-end.
    FEATURE_FLAG: str | None = None
    ALLOWED_HOSTS: str | None = None


def _service(env_dir: Path, env_lines: str = "") -> ConfigService:
    if env_lines:
        (env_dir / ".env").write_text(env_lines, encoding="utf-8")
    return ConfigService(_AppConfig())


def test_get_returns_value_when_set(env_dir: Path) -> None:
    service = _service(env_dir, "APP_NAME=hello\n")
    assert service.get("APP_NAME") == "hello"


def test_get_returns_default_when_value_is_none(env_dir: Path) -> None:
    service = _service(env_dir)
    assert service.get("FEATURE_FLAG", "off") == "off"


def test_require_returns_value_when_set(env_dir: Path) -> None:
    service = _service(env_dir, "APP_NAME=hello\n")
    assert service.require("APP_NAME") == "hello"


def test_require_raises_config_missing_error_when_value_is_none(
    env_dir: Path,
) -> None:
    service = _service(env_dir)
    with pytest.raises(ConfigMissingError) as info:
        service.require("FEATURE_FLAG")
    assert "FEATURE_FLAG" in str(info.value)


def test_get_int_coerces_string_to_int(env_dir: Path) -> None:
    service = _service(env_dir, "APP_PORT=8080\n")
    assert service.get_int("APP_PORT") == 8080


def test_get_int_returns_default_when_missing(env_dir: Path) -> None:
    service = _service(env_dir)
    assert service.get_int("MISSING_PORT", default=4242) == 4242


def test_get_int_raises_for_malformed_value(env_dir: Path) -> None:
    service = _service(env_dir, "APP_PORT=not-a-number\n")
    with pytest.raises(ValueError, match="APP_PORT"):
        service.get_int("APP_PORT")


def test_get_int_raises_config_missing_when_no_default(env_dir: Path) -> None:
    service = _service(env_dir)
    with pytest.raises(ConfigMissingError, match="MISSING_PORT"):
        service.get_int("MISSING_PORT")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("True", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
    ],
)
def test_get_bool_coerces_common_strings(env_dir: Path, raw: str, expected: bool) -> None:
    service = _service(env_dir, f"FEATURE_FLAG={raw}\n")
    assert service.get_bool("FEATURE_FLAG") is expected


def test_get_bool_returns_default_when_missing(env_dir: Path) -> None:
    service = _service(env_dir)
    assert service.get_bool("FEATURE_FLAG", default=True) is True


def test_get_bool_raises_config_missing_when_no_default(env_dir: Path) -> None:
    service = _service(env_dir)
    with pytest.raises(ConfigMissingError, match="FEATURE_FLAG"):
        service.get_bool("FEATURE_FLAG")


def test_get_bool_raises_for_garbage_value(env_dir: Path) -> None:
    service = _service(env_dir, "FEATURE_FLAG=maybe\n")
    with pytest.raises(ValueError, match="FEATURE_FLAG"):
        service.get_bool("FEATURE_FLAG")


def test_get_list_splits_on_separator(env_dir: Path) -> None:
    service = _service(env_dir, "ALLOWED_HOSTS=a,b,c\n")
    assert service.get_list("ALLOWED_HOSTS") == ["a", "b", "c"]


def test_get_list_uses_custom_separator(env_dir: Path) -> None:
    service = _service(env_dir, "ALLOWED_HOSTS=a;b;c\n")
    assert service.get_list("ALLOWED_HOSTS", separator=";") == ["a", "b", "c"]


def test_get_list_returns_default_when_missing(env_dir: Path) -> None:
    service = _service(env_dir)
    assert service.get_list("ALLOWED_HOSTS", default=["fallback"]) == ["fallback"]


def test_get_list_strips_whitespace_and_drops_empty_fragments(env_dir: Path) -> None:
    service = _service(env_dir, "ALLOWED_HOSTS=a, , b ,,c\n")
    assert service.get_list("ALLOWED_HOSTS") == ["a", "b", "c"]


@pytest.mark.parametrize(
    ("app_env", "expect_prod", "expect_dev", "expect_test"),
    [
        ("production", True, False, False),
        ("development", False, True, False),
        ("test", False, False, True),
        ("staging", False, False, False),
    ],
)
def test_env_predicates_reflect_app_env(
    env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
    expect_prod: bool,
    expect_dev: bool,
    expect_test: bool,
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    service = ConfigService(_AppConfig())
    assert service.is_production() is expect_prod
    assert service.is_development() is expect_dev
    assert service.is_test() is expect_test


def test_unrelated_env_var_does_not_change_app_env_predicates(
    env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SOME_OTHER_VAR", "irrelevant")
    service = ConfigService(_AppConfig())
    assert service.is_production() is True
    assert service.is_development() is False
    assert service.is_test() is False
