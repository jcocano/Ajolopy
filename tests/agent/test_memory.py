"""Tests for the Memory escape hatch.

Covers the "Memory escape hatch" acceptance group plus the in-package
defaults provided by AJ-1 (full backend support lands in AJ-24).
"""

from typing import TYPE_CHECKING, override

import pytest

from ajolopy import Agent
from ajolopy.memory import InMemoryMemory, Memory

if TYPE_CHECKING:
    from ajolopy.providers import Message

    from .conftest import FakeProvider


@pytest.mark.asyncio
async def test_memory_url_string_is_passed_to_in_memory_factory(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        memory="redis://localhost:6379",
    )
    class Demo:
        pass

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    memory = runtime._memory
    assert isinstance(memory, InMemoryMemory)
    # The URL is preserved as metadata so AJ-24 can swap in a real backend.
    assert memory.url == "redis://localhost:6379"


@pytest.mark.asyncio
async def test_memory_subclass_get_and_append_are_called(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    class RecordingMemory(Memory):
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str | None]] = []
            self.store: list[Message] = []

        @override
        async def get(self, session_id: str) -> list[Message]:
            self.calls.append(("get", session_id, None))
            return list(self.store)

        @override
        async def append(self, session_id: str, message: Message) -> None:
            self.calls.append(("append", session_id, message.content))
            self.store.append(message)

    @Agent(
        model="claude-sonnet-4-7",
        system="…",
        memory=RecordingMemory,
    )
    class Demo:
        pass

    instance = Demo()
    await instance.run("hello world")  # type: ignore[attr-defined]
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    memory = runtime._memory
    assert isinstance(memory, RecordingMemory)
    # First call loads history, two append calls (user + assistant) write it.
    op_names = [op for op, _, _ in memory.calls]
    assert op_names == ["get", "append", "append"]
