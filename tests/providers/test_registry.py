"""Tests for register_provider / get_provider_class.

Covers the "Registry" and second half of "Negative cases" acceptance groups.
"""

from typing import TYPE_CHECKING, override

import pytest

from ajolopy.providers import (
    Chunk,
    LLMProvider,
    Message,
    ProviderNotRegisteredError,
    Response,
    Tool,
    get_provider_class,
    register_provider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeProvider(LLMProvider):
    """Minimal concrete LLMProvider used by tests that need a real subclass."""

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        return Response(text="fake")

    @override
    def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:
        async def _it() -> AsyncIterator[Chunk]:
            yield Chunk(delta="fake", finish_reason="stop")

        return _it()

    @override
    async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
        return [[0.0]]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        return 0

    @override
    def supports_prompt_caching(self) -> bool:
        return False

    @override
    def supports_tool_calling(self) -> bool:
        return False


class AnotherFakeProvider(FakeProvider):
    pass


def test_register_and_get_round_trip() -> None:
    register_provider("anthropic", FakeProvider)
    assert get_provider_class("anthropic") is FakeProvider


def test_re_registration_rejected_by_default() -> None:
    register_provider("anthropic", FakeProvider)
    with pytest.raises(ValueError, match="already registered"):
        register_provider("anthropic", AnotherFakeProvider)
    assert get_provider_class("anthropic") is FakeProvider


def test_re_registration_with_overwrite_replaces() -> None:
    register_provider("anthropic", FakeProvider)
    register_provider("anthropic", AnotherFakeProvider, overwrite=True)
    assert get_provider_class("anthropic") is AnotherFakeProvider


def test_get_provider_class_unknown_key_raises_with_known_keys() -> None:
    register_provider("anthropic", FakeProvider)
    register_provider("openai", FakeProvider)
    with pytest.raises(ProviderNotRegisteredError) as info:
        get_provider_class("does-not-exist")
    message = str(info.value)
    assert "does-not-exist" in message
    assert "anthropic" in message
    assert "openai" in message


def test_register_provider_rejects_non_llm_provider_class() -> None:
    class NotAProvider:
        pass

    with pytest.raises(TypeError, match="LLMProvider subclass"):
        register_provider("anthropic", NotAProvider)  # type: ignore[arg-type]


def test_register_provider_rejects_instance_instead_of_class() -> None:
    instance = FakeProvider()
    with pytest.raises(TypeError, match="LLMProvider subclass"):
        register_provider("anthropic", instance)  # type: ignore[arg-type]
