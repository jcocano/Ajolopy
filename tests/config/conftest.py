"""Shared fixtures for config tests.

Every test runs from a fresh temporary directory so the `.env` and `.env.test`
files they write do not pollute each other or the repo root. ``APP_ENV`` is
cleared before each test so APP_ENV-dependent behaviour starts from a known
baseline; tests that need an APP_ENV value set it via ``monkeypatch``.
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def env_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_ENV", raising=False)
    return tmp_path
