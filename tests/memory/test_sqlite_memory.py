"""Acceptance tests for :class:`SQLiteMemory`."""

from pathlib import Path

import pytest

from ajolopy.memory import SQLiteMemory
from ajolopy.memory.errors import MemoryConfigError
from ajolopy.providers import Message, ToolCall


@pytest.mark.asyncio
async def test_in_memory_round_trip_preserves_messages() -> None:
    memory = SQLiteMemory(":memory:")
    await memory.append("s1", Message(role="user", content="hello"))
    await memory.append(
        "s1",
        Message(
            role="assistant",
            content="hi back",
            tool_calls=[ToolCall(id="tc1", name="foo", arguments={"a": 1})],
        ),
    )
    rows = await memory.get("s1")
    assert [(m.role, m.content) for m in rows] == [("user", "hello"), ("assistant", "hi back")]
    assert rows[1].tool_calls[0].id == "tc1"
    assert rows[1].tool_calls[0].arguments == {"a": 1}


@pytest.mark.asyncio
async def test_file_path_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deeper" / "memory.db"
    memory = SQLiteMemory(str(nested))
    await memory.append("s1", Message(role="user", content="durable"))
    assert nested.parent.exists()
    rows = await memory.get("s1")
    assert rows[0].content == "durable"


@pytest.mark.asyncio
async def test_schema_creation_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    first = SQLiteMemory(str(path))
    await first.append("s1", Message(role="user", content="first"))
    # Second instance pointed at the same file should reuse the schema
    # rather than fail with "table already exists".
    second = SQLiteMemory(str(path))
    await second.append("s1", Message(role="user", content="second"))
    rows = await second.get("s1")
    assert [m.content for m in rows] == ["first", "second"]


@pytest.mark.asyncio
async def test_clear_removes_only_target_session() -> None:
    memory = SQLiteMemory(":memory:")
    await memory.append("s1", Message(role="user", content="a"))
    await memory.append("s2", Message(role="user", content="b"))
    await memory.clear("s1")
    assert await memory.get("s1") == []
    assert (await memory.get("s2"))[0].content == "b"


def test_empty_path_raises_config_error() -> None:
    with pytest.raises(MemoryConfigError):
        SQLiteMemory("")
