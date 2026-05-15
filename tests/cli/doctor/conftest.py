"""Shared fixtures for ``ajolopy doctor`` CLI tests.

The doctor exercises a *lot* of network-aware code paths, so every
fixture here is built to keep the tests offline and deterministic:

- ``clean_env`` blanks every env var the doctor inspects so a developer
  running pytest with ``ANTHROPIC_API_KEY`` exported in their shell does
  not silently flip the suite green.
- ``mcp_registry_reset`` returns a fresh ``MCPRegistry`` before every
  test so the mcp_servers check observes exactly what the test stamps.
"""

import os
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip env vars the doctor's checks read so each test is hermetic.

    ``VIRTUAL_ENV`` is also cleared so the ``venv_present`` check sees
    only what each test deliberately sets.
    """
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "VIRTUAL_ENV",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def with_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    return "sk-ant-test"


@pytest.fixture
def with_openai_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    return "sk-openai-test"


@pytest.fixture
def with_gemini_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    return "gemini-test"


@pytest.fixture
def mcp_registry_reset() -> Iterator[Any]:
    """Reset the process-wide MCP registry before/after each test.

    Yields the fresh registry so the test can register classes onto it
    directly. ``reset_mcp_registry`` runs again on teardown so state
    never leaks into other test files.
    """
    from ajolopy.mcp.registry import reset_mcp_registry

    registry = reset_mcp_registry()
    yield registry
    reset_mcp_registry()


@pytest.fixture
def env_snapshot() -> dict[str, str]:
    """Snapshot of ``os.environ`` to assert deltas in the env_validation check."""
    return dict(os.environ)
