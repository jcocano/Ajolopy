"""Integration tests: ``@Agent`` + the new memory backends."""

from typing import TYPE_CHECKING

import pytest

from ajolopy import Agent
from ajolopy.memory import InMemoryMemory

if TYPE_CHECKING:
    from tests.agent.conftest import FakeProvider


@pytest.mark.asyncio
async def test_memory_url_short_form_attaches_in_memory(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-opus-4-7", system="…", memory="memory://")
    class Demo:
        pass

    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    assert isinstance(runtime._memory, InMemoryMemory)


@pytest.mark.asyncio
async def test_second_turn_sees_first_turn_in_history(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-opus-4-7", system="…", memory="memory://")
    class Demo:
        pass

    instance = Demo()
    await instance.run("hello")  # type: ignore[attr-defined]
    await instance.run("again")  # type: ignore[attr-defined]
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    memory = runtime._memory
    assert isinstance(memory, InMemoryMemory)
    transcript = await memory.get("default")
    # Two turns x (user + assistant) = 4 messages.
    assert len(transcript) == 4
    assert transcript[0].role == "user"
    assert transcript[0].content == "hello"
    assert transcript[2].role == "user"
    assert transcript[2].content == "again"


@pytest.mark.asyncio
async def test_shared_instance_lets_two_agents_share_history(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    shared = InMemoryMemory()

    @Agent(model="claude-opus-4-7", system="…", memory=shared)
    class A:
        pass

    @Agent(model="claude-opus-4-7", system="…", memory=shared)
    class B:
        pass

    await A().run("from A")  # type: ignore[attr-defined]
    await B().run("from B")  # type: ignore[attr-defined]
    transcript = await shared.get("default")
    # Two runs x (user + assistant) = 4 messages, in the order they ran.
    assert [m.content for m in transcript if m.role == "user"] == ["from A", "from B"]
