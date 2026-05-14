"""Shared fixtures for the ``@Workflow`` test suite.

Reuses the agent suite's ``FakeProvider`` so the provider registry
behaves identically across both surfaces. The repo-wide
``isolate_registry`` fixture (in ``tests/conftest.py``) snapshots and
restores the registry between tests, so each workflow test starts from
a clean baseline.
"""

from collections.abc import AsyncIterator
from typing import override

import pytest

from ajolopy.providers import Chunk, Message, Tool, register_provider
from tests.agent.conftest import FakeProvider


class ScriptedStreamProvider(FakeProvider):
    """FakeProvider variant that returns scripted Chunk lists per stream call.

    ``stream_rounds`` is a list of lists of :class:`Chunk` objects; the
    Nth call to :meth:`stream` yields the Nth list. When the round list is
    exhausted the provider falls back to a default ``stop`` chunk so
    misuse surfaces visibly rather than hanging.
    """

    def __init__(self) -> None:
        super().__init__()
        self.stream_rounds: list[list[Chunk]] = []
        self._round_index = 0

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
        if self._round_index < len(self.stream_rounds):
            events = self.stream_rounds[self._round_index]
            self._round_index += 1
        else:
            events = [Chunk(delta="default", finish_reason="stop")]
        should_raise = self.raise_on_stream

        async def _it() -> AsyncIterator[Chunk]:
            if should_raise is not None:
                raise should_raise
            for event in events:
                yield event

        return _it()


@pytest.fixture
def scripted_stream_provider() -> type[ScriptedStreamProvider]:
    """Register :class:`ScriptedStreamProvider` under ``anthropic`` and return it."""
    register_provider("anthropic", ScriptedStreamProvider, overwrite=True)
    return ScriptedStreamProvider


__all__ = [
    "ScriptedStreamProvider",
    "scripted_stream_provider",
]
