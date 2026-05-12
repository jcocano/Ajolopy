"""Tests for the custom field_validator escape hatch.

Covers the "Custom validation hook" acceptance group.
"""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError, field_validator

from ajolopy.config import BaseConfig

if TYPE_CHECKING:
    from pathlib import Path


class _SecretConfig(BaseConfig):
    APP_SECRET: str

    @field_validator("APP_SECRET")
    @classmethod
    def reject_placeholder(cls, value: str) -> str:
        if value == "change-me":
            raise ValueError("APP_SECRET must be changed from the placeholder value")
        return value


def test_field_validator_message_surfaces_in_validation_error(
    env_dir: Path,
) -> None:
    (env_dir / ".env").write_text("APP_SECRET=change-me\n", encoding="utf-8")
    with pytest.raises(ValidationError) as info:
        # reportCallIssue: APP_SECRET is supplied via the dotenv source at runtime.
        _SecretConfig()  # pyright: ignore[reportCallIssue]
    assert "must be changed from the placeholder value" in str(info.value)


def test_field_validator_passes_through_valid_values(
    env_dir: Path,
) -> None:
    (env_dir / ".env").write_text("APP_SECRET=a-strong-value\n", encoding="utf-8")
    # reportCallIssue: APP_SECRET is supplied via the dotenv source at runtime.
    config = _SecretConfig()  # pyright: ignore[reportCallIssue]
    # S105: literal value here is the test fixture, not a hardcoded secret.
    assert config.APP_SECRET == "a-strong-value"  # noqa: S105
