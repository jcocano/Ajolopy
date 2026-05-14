"""Threshold resolution: explicit arg > LOG_LEVEL env var > env default."""

import logging
import os
from collections.abc import Iterator

import pytest

from ajolopy.observability.logging import (
    _resolve_level,
    configure_logging,
)


@pytest.fixture(autouse=True)
def clear_log_level_env_var() -> Iterator[None]:
    """Clear ``LOG_LEVEL`` around each test (the autouse logging reset
    fixture lives in the directory ``conftest.py``).
    """
    saved = os.environ.pop("LOG_LEVEL", None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ["LOG_LEVEL"] = saved
        else:
            os.environ.pop("LOG_LEVEL", None)


def test_development_defaults_to_debug() -> None:
    configure_logging("development")
    assert logging.getLogger("ajolopy.test_module").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_production_defaults_to_info() -> None:
    configure_logging("production")
    assert logging.getLogger("ajolopy.test_module").getEffectiveLevel() == logging.INFO
    assert logging.getLogger().getEffectiveLevel() == logging.INFO


def test_test_env_defaults_to_warning() -> None:
    configure_logging("test")
    assert logging.getLogger("ajolopy.test_module").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger().getEffectiveLevel() == logging.WARNING


def test_log_level_env_var_overrides_env_default() -> None:
    os.environ["LOG_LEVEL"] = "ERROR"
    configure_logging("development")
    assert logging.getLogger().getEffectiveLevel() == logging.ERROR


@pytest.mark.parametrize("raw", ["debug", "Debug", "DEBUG", " debug "])
def test_log_level_parsing_is_case_insensitive(raw: str) -> None:
    os.environ["LOG_LEVEL"] = raw
    configure_logging("production")
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_invalid_log_level_raises_value_error_before_installing() -> None:
    os.environ["LOG_LEVEL"] = "chatty"
    with pytest.raises(ValueError, match="chatty"):
        configure_logging("development")
    # No handler should have been attached because resolve_level ran first.
    assert not any(getattr(h, "_ajolopy_installed", False) for h in logging.getLogger().handlers)


def test_explicit_log_level_argument_wins_over_env_var_and_default() -> None:
    os.environ["LOG_LEVEL"] = "INFO"
    configure_logging("development", log_level="ERROR")
    assert logging.getLogger().getEffectiveLevel() == logging.ERROR


def test_resolve_level_helper_matches_documented_table() -> None:
    # Direct unit-level coverage so future refactors keep the table honest.
    assert _resolve_level("development", None) == logging.DEBUG
    assert _resolve_level("production", None) == logging.INFO
    assert _resolve_level("test", None) == logging.WARNING
    assert _resolve_level("development", "warning") == logging.WARNING
