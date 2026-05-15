"""Per-prefix client resolution tests for UniversalOpenAIProvider.

Covers the "Per-prefix client resolution" acceptance group: each
prefix's lazy env-var read, the cached-client invariant (one
AsyncOpenAI instance per prefix for the lifetime of the provider),
and Ollama's special case (no API key).
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ajolopy.providers.universal_openai import (
    UniversalOpenAIProvider,
    UniversalProviderConfigError,
)

# (prefix, env_var, expected_base_url) — mirrors the spec's table.
_API_KEY_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    ("together", "TOGETHER_API_KEY", "https://api.together.xyz/v1"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
)


@pytest.mark.parametrize(("prefix", "env_var", "expected_url"), _API_KEY_PREFIXES)
def test_each_prefix_reads_its_env_var_and_default_base_url(
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    env_var: str,
    expected_url: str,
) -> None:
    # Set just this prefix's env var; the resolver must pick it up and
    # construct an AsyncOpenAI with the spec's default base_url.
    monkeypatch.setenv(env_var, f"sk-{prefix}-test")
    captured: dict[str, Any] = {}

    def _capture(*args: Any, **kwargs: Any) -> MagicMock:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return MagicMock(name=f"AsyncOpenAI-{prefix}")

    provider = UniversalOpenAIProvider()
    with patch("openai.AsyncOpenAI", side_effect=_capture):
        provider._resolve_client(prefix)
    assert captured["kwargs"]["base_url"] == expected_url
    assert captured["kwargs"]["api_key"] == f"sk-{prefix}-test"


@pytest.mark.parametrize(("prefix", "env_var", "_url"), _API_KEY_PREFIXES)
def test_missing_env_var_raises_typed_config_error(
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    env_var: str,
    _url: str,
) -> None:
    # The autouse fixture already cleared every per-prefix env var; we
    # only need to assert the typed error mentions both the prefix and
    # the env-var name so users know exactly what to fix.
    monkeypatch.delenv(env_var, raising=False)
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderConfigError) as exc_info:
        provider._resolve_client(prefix)
    msg = str(exc_info.value)
    assert env_var in msg
    assert prefix in msg


def test_groq_client_is_cached_after_first_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Per spec: AsyncOpenAI is constructed exactly once for a prefix
    # across multiple requests with different models under the same
    # prefix.
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    call_count = {"n": 0}

    def _factory(*_args: Any, **_kwargs: Any) -> MagicMock:
        call_count["n"] += 1
        return MagicMock(name="AsyncOpenAI-groq")

    provider = UniversalOpenAIProvider()
    with patch("openai.AsyncOpenAI", side_effect=_factory):
        first = provider._resolve_client("groq")
        second = provider._resolve_client("groq")
    assert first is second
    assert call_count["n"] == 1


def test_ollama_builds_without_consulting_api_key_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ollama runs locally and uses the literal "ollama" placeholder for
    # the API key. The resolver must NOT touch any per-prefix API key
    # env var to build the client. (Reading ``OLLAMA_BASE_URL`` for the
    # base-URL override is expected — AJ-68 — but it must be unset for
    # this test so the default URL is still picked.)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    accessed: list[str] = []
    real_environ_get = __import__("os").environ.get

    def _spy_get(key: str, default: object = None) -> object:
        accessed.append(key)
        return real_environ_get(key, default)

    monkeypatch.setattr("os.environ.get", _spy_get)
    captured: dict[str, Any] = {}

    def _capture(*args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        return MagicMock(name="AsyncOpenAI-ollama")

    provider = UniversalOpenAIProvider()
    with patch("openai.AsyncOpenAI", side_effect=_capture):
        provider._resolve_client("ollama")
    # The literal "ollama" is forwarded as api_key, and the default
    # base_url for local Ollama is in place.
    assert captured["kwargs"]["api_key"] == "ollama"
    assert captured["kwargs"]["base_url"] == "http://localhost:11434/v1"
    # No per-prefix API key env var was probed during resolution.
    assert not any(name.endswith("_API_KEY") for name in accessed)
