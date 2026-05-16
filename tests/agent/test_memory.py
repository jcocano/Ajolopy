"""Tests for the Memory escape hatch on ``@Agent``.

End-to-end backend coverage lives in ``tests/memory/``; this file pins
the integration contract between :func:`Agent` and the memory layer:

- The ``memory=`` kwarg accepts a :class:`Memory` subclass and the
  runtime exercises ``get``/``append`` in the documented order.
- A passed-through :class:`Memory` instance is reused verbatim by the
  runtime (no implicit copy / clone).
"""

from typing import TYPE_CHECKING, override

import pytest

from ajolopy import Agent
from ajolopy.memory import InMemoryMemory, Memory

if TYPE_CHECKING:
    from ajolopy.providers import Message

    from .conftest import FakeProvider


@pytest.mark.asyncio
async def test_memory_instance_is_attached_verbatim(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    shared = InMemoryMemory()

    @Agent(
        model="claude-opus-4-7",
        system="…",
        memory=shared,
    )
    class Demo:
        pass

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert runtime._memory is shared


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

        @override
        async def clear(self, session_id: str) -> None:
            self.calls.append(("clear", session_id, None))
            self.store.clear()

    @Agent(
        model="claude-opus-4-7",
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
