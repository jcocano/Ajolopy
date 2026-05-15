"""Per-prefix ``${PREFIX}_BASE_URL`` environment-variable override (AJ-68).

Covers the new env-var-backed default for the base URL:

- The provider reads ``${PREFIX.upper()}_BASE_URL`` lazily on the first
  request for a prefix and uses it as the base URL.
- Constructor ``base_urls={...}`` keeps absolute precedence over the env
  var (existing behaviour preserved).
- Empty string falls through to the baked-in default.
- The read is lazy: setting the env var *after* ``__init__`` and before
  the first ``_resolve_client(prefix)`` call still takes effect.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ajolopy.providers.universal_openai import UniversalOpenAIProvider

# (prefix, env_var, baked_default_url) — mirrors ``_PREFIX_DEFAULTS``.
_BASE_URL_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("ollama", "OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    ("groq", "GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    ("together", "TOGETHER_BASE_URL", "https://api.together.xyz/v1"),
    ("mistral", "MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
    ("deepseek", "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    ("openrouter", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
)


def _set_api_key_for(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    """Provide a stub API key so the resolver does not raise mid-test.

    Ollama needs no env var (it accepts the literal ``"ollama"``); every
    other prefix requires its ``api_key_env`` to be set before the
    resolver builds the client.
    """
    api_key_env = {
        "groq": "GROQ_API_KEY",
        "together": "TOGETHER_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(prefix)
    if api_key_env is not None:
        monkeypatch.setenv(api_key_env, f"sk-{prefix}-stub")


@pytest.mark.parametrize(("prefix", "env_var", "_default_url"), _BASE_URL_PREFIXES)
def test_env_var_overrides_baked_default_for_each_prefix(
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    env_var: str,
    _default_url: str,
) -> None:
    # Setting ``${PREFIX}_BASE_URL`` must reach ``openai.AsyncOpenAI`` as
    # the ``base_url`` argument, regardless of which known prefix the
    # caller targets.
    custom_url = f"https://internal.example.test/{prefix}/v1"
    monkeypatch.setenv(env_var, custom_url)
    _set_api_key_for(monkeypatch, prefix)

    captured: dict[str, Any] = {}

    def _capture(*_args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        return MagicMock(name=f"AsyncOpenAI-{prefix}")

    provider = UniversalOpenAIProvider()
    with patch("openai.AsyncOpenAI", side_effect=_capture):
        provider._resolve_client(prefix)
    assert captured["kwargs"]["base_url"] == custom_url


@pytest.mark.parametrize(("prefix", "env_var", "_default_url"), _BASE_URL_PREFIXES)
def test_constructor_base_urls_kwarg_wins_over_env_var(
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    env_var: str,
    _default_url: str,
) -> None:
    # ``base_urls=`` is the highest-priority URL source (only ``clients=``
    # ranks above it, and that path skips ``_resolve_base_url`` entirely
    # because the cache short-circuits the build). Setting both must
    # surface the constructor kwarg.
    monkeypatch.setenv(env_var, "https://env-value.example.test/v1")
    _set_api_key_for(monkeypatch, prefix)
    kwarg_url = f"https://kwarg-value.example.test/{prefix}/v1"

    captured: dict[str, Any] = {}

    def _capture(*_args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        return MagicMock(name=f"AsyncOpenAI-{prefix}")

    provider = UniversalOpenAIProvider(base_urls={prefix: kwarg_url})
    with patch("openai.AsyncOpenAI", side_effect=_capture):
        provider._resolve_client(prefix)
    assert captured["kwargs"]["base_url"] == kwarg_url


@pytest.mark.parametrize(("prefix", "env_var", "default_url"), _BASE_URL_PREFIXES)
def test_empty_env_var_falls_through_to_baked_default(
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    env_var: str,
    default_url: str,
) -> None:
    # Empty strings are treated as "not set" — same convention as
    # ``_resolve_api_key`` — so they must fall through to the baked-in
    # default URL rather than be forwarded as an empty ``base_url``.
    monkeypatch.setenv(env_var, "")
    _set_api_key_for(monkeypatch, prefix)

    captured: dict[str, Any] = {}

    def _capture(*_args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        return MagicMock(name=f"AsyncOpenAI-{prefix}")

    provider = UniversalOpenAIProvider()
    with patch("openai.AsyncOpenAI", side_effect=_capture):
        provider._resolve_client(prefix)
    assert captured["kwargs"]["base_url"] == default_url


def test_env_var_is_read_lazily_after_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Construction itself must not touch the environment — the env var
    # is consulted only on the first request that builds the client.
    # Mutating it after ``__init__`` but before that build must still
    # take effect, proving the read happens in ``_resolve_client``.
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    provider = UniversalOpenAIProvider()

    lazy_url = "http://lazy-ollama.example.test/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", lazy_url)

    captured: dict[str, Any] = {}

    def _capture(*_args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        return MagicMock(name="AsyncOpenAI-ollama")

    with patch("openai.AsyncOpenAI", side_effect=_capture):
        provider._resolve_client("ollama")
    assert captured["kwargs"]["base_url"] == lazy_url


def test_env_var_not_reread_after_client_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Once a prefix's client is built, the env var must not be re-read
    # on subsequent requests — the cache wins. Changing
    # ``OLLAMA_BASE_URL`` after the first build does not invalidate the
    # cached client.
    initial = "http://first-ollama.example.test/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", initial)
    call_count = {"n": 0}
    captured: list[dict[str, Any]] = []

    def _factory(*_args: Any, **kwargs: Any) -> MagicMock:
        call_count["n"] += 1
        captured.append(kwargs)
        return MagicMock(name="AsyncOpenAI-ollama")

    provider = UniversalOpenAIProvider()
    with patch("openai.AsyncOpenAI", side_effect=_factory):
        first = provider._resolve_client("ollama")
        # Mutate the env after the first build — should be ignored.
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://second-ollama.example.test/v1")
        second = provider._resolve_client("ollama")

    assert first is second
    assert call_count["n"] == 1
    assert captured[0]["base_url"] == initial


def test_env_var_is_not_read_at_init_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Constructing the provider must not touch ``os.environ`` for any
    # ``_BASE_URL`` env var. The read is deferred to ``_resolve_client``
    # to keep imports and instantiation side-effect-free.
    accessed: list[str] = []
    real_environ_get = __import__("os").environ.get

    def _spy_get(key: str, default: object = None) -> object:
        accessed.append(key)
        return real_environ_get(key, default)

    monkeypatch.setattr("os.environ.get", _spy_get)
    _ = UniversalOpenAIProvider()
    assert not any(name.endswith("_BASE_URL") for name in accessed)
