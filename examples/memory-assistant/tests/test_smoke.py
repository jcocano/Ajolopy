"""Smoke test — verifies the example imports, decorates, and partitions.

The test deliberately does NOT call any LLM provider, does NOT
``monkeypatch`` the SDK, and does NOT require a running Redis. It only
asserts:

- The decorator metadata lands (``@Agent`` / ``@Tool`` / ``@Stream``).
- :class:`SessionScopedMemory` correctly remaps the agent runtime's
  hardcoded ``"default"`` session_id onto the
  :class:`contextvars.ContextVar` value.
- Two different ``session_scope`` blocks see independent transcripts
  even when they share the same underlying backend instance.
"""

import pytest
from memory_assistant.agents.tracker import ChatRequest, Tracker
from memory_assistant.app_module import AppModule
from memory_assistant.memory import SessionScopedMemory, session_scope

from ajolopy import AjolopyFactory
from ajolopy.memory import InMemoryMemory, Memory
from ajolopy.providers import Message


def test_tracker_agent_is_decorated() -> None:
    """The ``Tracker`` class survives import and exposes ``run`` / ``stream``."""
    assert hasattr(Tracker, "_agent_runtime")
    assert callable(getattr(Tracker, "run", None))
    assert callable(getattr(Tracker, "stream", None))


def test_record_task_tool_is_registered() -> None:
    """``Tracker.record_task`` carries the ``@Tool`` marker."""
    assert hasattr(Tracker.record_task, "__ajolopy_tool__")


def test_chat_request_validates_session_id_and_message() -> None:
    """The Pydantic body model rejects empty strings on both required fields."""
    valid = ChatRequest.model_validate({"message": "hi", "session_id": "alice"})
    assert valid.message == "hi"
    assert valid.session_id == "alice"

    with pytest.raises(ValueError):
        ChatRequest.model_validate({"message": "hi", "session_id": ""})
    with pytest.raises(ValueError):
        ChatRequest.model_validate({"message": "", "session_id": "alice"})


def test_tracker_memory_is_session_scoped() -> None:
    """The runtime's ``memory`` attribute is the wrapped, session-aware backend.

    ``REDIS_URL=memory://`` (set in ``conftest.py``) resolves to
    :class:`InMemoryMemory`, which the example wraps in
    :class:`SessionScopedMemory` before passing to ``@Agent``.
    """
    runtime = Tracker._agent_runtime  # type: ignore[attr-defined]
    memory = runtime._memory  # type: ignore[attr-defined]
    assert isinstance(memory, SessionScopedMemory)
    assert isinstance(memory.inner, InMemoryMemory)


@pytest.mark.asyncio
async def test_app_boots_and_mounts_chat_route() -> None:
    """AJ-98 regression: ``AjolopyFactory.create`` must boot + mount ``/chat``.

    Drives the agent's ``@Stream("/chat")`` handler — whose
    ``AsyncGenerator`` return annotation is the one that previously
    crashed under PEP 649 — through the framework's ``mount_streams``
    path. The assertion is that the route lands on ``app.http``;
    without the AJ-98 fix the factory raises ``NameError`` before we
    ever get here.
    """
    app = await AjolopyFactory.create(AppModule)
    try:
        paths = {getattr(route, "path", "") for route in app.http.routes}
        assert "/chat" in paths, (
            f"Expected /chat mounted on memory-assistant app; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()


async def test_session_scope_partitions_history() -> None:
    """Two ``session_scope`` blocks must see independent transcripts.

    This is the leak-prevention contract the example demonstrates: the
    agent runtime always asks the memory for ``session_id="default"``,
    but the wrapper substitutes the contextvar's value so each scope
    only sees its own history.
    """
    inner: Memory = InMemoryMemory()
    wrapped = SessionScopedMemory(inner)

    with session_scope("alice"):
        await wrapped.append("default", Message(role="user", content="alice-task"))
        alice_history = await wrapped.get("default")

    with session_scope("bob"):
        bob_history = await wrapped.get("default")

    assert [m.content for m in alice_history] == ["alice-task"]
    assert bob_history == []
