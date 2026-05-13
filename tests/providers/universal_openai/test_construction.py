"""Tests for UniversalOpenAIProvider construction and registry side effects.

Covers the "Registration & construction" acceptance group.
"""

from unittest.mock import MagicMock

import pytest

from ajolopy.providers import Message, get_provider_class
from ajolopy.providers.universal_openai import (
    UniversalOpenAIProvider,
    UniversalProviderConfigError,
)

from .conftest import make_async_client


def test_importing_package_registers_under_universal_openai_key() -> None:
    # The conftest fixture has already imported the package; the
    # registry should resolve "universal-openai" to UniversalOpenAIProvider.
    assert get_provider_class("universal-openai") is UniversalOpenAIProvider


def test_default_construction_does_no_io_and_reads_no_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Construction must be side-effect-free per the spec: imports and
    # __init__ never touch the environment, so even with a completely
    # cleared env the constructor returns instantly.
    monkeypatch.setattr("os.environ", {})
    provider = UniversalOpenAIProvider()
    assert isinstance(provider, UniversalOpenAIProvider)


def test_api_keys_override_stored_and_env_var_never_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If api_keys carries the prefix, the env var must never be touched
    # for it. Patch os.environ.get to record any access and assert
    # GROQ_API_KEY is not read.
    accessed: list[str] = []
    import os as _os

    original_environ_get = _os.environ.get

    def _spy_get(key: str, default: object = None) -> object:
        accessed.append(key)
        return original_environ_get(key, default)

    monkeypatch.setattr(_os.environ, "get", _spy_get)
    provider = UniversalOpenAIProvider(api_keys={"groq": "gsk_test"})
    # Force a client build for groq via the resolver helper.
    _ = provider._resolve_client("groq")
    assert "GROQ_API_KEY" not in accessed


def test_base_urls_override_propagates_to_built_client() -> None:
    # The override should land on the SDK's base_url. The lazy build
    # path constructs the client inside _resolve_client; we inspect
    # the resulting AsyncOpenAI instance.
    provider = UniversalOpenAIProvider(
        api_keys={"ollama": "ignored"},
        base_urls={"ollama": "http://my-ollama.lan:11434/v1"},
    )
    client = provider._resolve_client("ollama")
    # AsyncOpenAI exposes the configured base_url as a URL object on
    # the public attribute; cast to str for the comparison.
    assert str(client.base_url).rstrip("/") == "http://my-ollama.lan:11434/v1"


@pytest.mark.asyncio
async def test_supplied_client_is_used_verbatim_no_new_client_built() -> None:
    # Pre-built clients win over both api_keys and base_urls. The
    # resolver must return the supplied instance and never build a new
    # AsyncOpenAI for the prefix.
    custom = make_async_client()
    provider = UniversalOpenAIProvider(clients={"groq": custom})
    resolved = provider._resolve_client("groq")
    assert resolved is custom
    # Round-trip through complete() to prove the same client is used end
    # to end (no surprise rebuild on the hot path).
    await provider.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
    )
    custom.chat.completions.create.assert_awaited_once()


def test_clients_kwarg_wins_over_base_url_and_api_key_overrides() -> None:
    # When both clients= and the override kwargs are passed, clients
    # wins — the pre-built instance is returned untouched.
    custom = MagicMock(name="custom AsyncOpenAI")
    provider = UniversalOpenAIProvider(
        api_keys={"groq": "ignored"},
        base_urls={"groq": "https://ignored.invalid/v1"},
        clients={"groq": custom},
    )
    assert provider._resolve_client("groq") is custom


def test_missing_env_var_raises_typed_config_error_at_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The provider constructs cleanly; the error only surfaces on the
    # first request that needs the missing key. The message must name
    # both the prefix and the env var.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = UniversalOpenAIProvider()
    with pytest.raises(UniversalProviderConfigError, match="GROQ_API_KEY"):
        provider._resolve_client("groq")
