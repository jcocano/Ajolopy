"""Shared fixtures for the ``@Eval`` test suite.

Reuses the agent suite's ``FakeProvider`` for any test that wires a
real ``@Agent`` target. JSONL fixtures live under
``tests/eval/fixtures/`` (AJ-25); the same files double as @Eval
datasets here.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import override

import pytest

from ajolopy.providers import Chunk, Message, Tool, register_provider
from tests.agent.conftest import FakeProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class ScriptedFake(FakeProvider):
    """FakeProvider whose ``complete`` returns scripted responses in order.

    Each call to ``complete`` pops the next entry off ``responses`` (the
    parent class behaviour); we override ``stream`` to return the same
    text as a one-chunk stream so streaming tests do not need to script
    Chunk lists separately.
    """

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
        if self.responses:
            response = self.responses.pop(0)
            chunks = [Chunk(delta=response.text, finish_reason="stop")]
        else:
            chunks = [Chunk(delta=f"reply from {model}", finish_reason="stop")]

        async def _it() -> AsyncIterator[Chunk]:
            for chunk in chunks:
                yield chunk

        self.stream_calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "cache": cache,
            }
        )
        return _it()


@pytest.fixture
def scripted_fake() -> type[ScriptedFake]:
    """Register :class:`ScriptedFake` under ``anthropic`` and return the class."""
    register_provider("anthropic", ScriptedFake, overwrite=True)
    return ScriptedFake


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


__all__ = [
    "FIXTURES_DIR",
    "ScriptedFake",
    "fixtures_dir",
    "scripted_fake",
]
