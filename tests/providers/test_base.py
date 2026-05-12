"""Tests for the LLMProvider ABC.

Covers the "Interface" and one half of the "Negative cases" acceptance group
in specs/llm-provider.md.
"""

from typing import TYPE_CHECKING, override

import pytest

from ajolopy.providers import Chunk, LLMProvider, Message, Response, Tool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def test_llm_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_subclass_missing_complete_cannot_instantiate() -> None:
    class MissingComplete(LLMProvider):
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
            raise NotImplementedError

        @override
        async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
            return []

        @override
        def count_tokens(self, *, model: str, text: str) -> int:
            return 0

        @override
        def supports_prompt_caching(self) -> bool:
            return False

        @override
        def supports_tool_calling(self) -> bool:
            return False

    with pytest.raises(TypeError):
        MissingComplete()  # type: ignore[abstract]


def test_subclass_missing_stream_cannot_instantiate() -> None:
    class MissingStream(LLMProvider):
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
            return Response(text="")

        @override
        async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
            return []

        @override
        def count_tokens(self, *, model: str, text: str) -> int:
            return 0

        @override
        def supports_prompt_caching(self) -> bool:
            return False

        @override
        def supports_tool_calling(self) -> bool:
            return False

    with pytest.raises(TypeError):
        MissingStream()  # type: ignore[abstract]


def test_fully_implemented_subclass_instantiates() -> None:
    class Complete(LLMProvider):
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
            return Response(text="ok")

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
                yield Chunk(delta="ok", finish_reason="stop")

            return _it()

        @override
        async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
            return [[0.0]]

        @override
        def count_tokens(self, *, model: str, text: str) -> int:
            return len(text)

        @override
        def supports_prompt_caching(self) -> bool:
            return True

        @override
        def supports_tool_calling(self) -> bool:
            return True

    provider = Complete()
    assert isinstance(provider, LLMProvider)
