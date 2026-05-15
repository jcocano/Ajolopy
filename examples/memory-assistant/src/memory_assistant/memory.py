"""Session-scoped :class:`ajolopy.memory.Memory` wrapper.

In v0.1, :class:`ajolopy.agent.runtime.AgentRuntime` calls every
:class:`Memory` method with a single hardcoded
``session_id == "default"`` — the per-call ``run(message)`` /
``stream(message)`` signature does not yet thread an explicit
``session_id`` kwarg. That keeps the killer-demo signature flat.

To partition history per HTTP user, this module wraps an inner backend
and substitutes the incoming ``session_id`` with the value carried in
a :class:`contextvars.ContextVar`. The :func:`session_scope` helper
context manager sets the var inside a request handler so the agent
runtime, the tools it dispatches, and any nested coroutine see a
consistent value — even under concurrent ``asyncio`` traffic.

This is the canonical "escape hatch" for the magical
``memory="redis://..."`` default: subclass :class:`Memory` and route
the call however your app needs.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, override

from ajolopy.memory import Memory

if TYPE_CHECKING:
    from collections.abc import Generator

    from ajolopy.providers import Message


# The fallback session_id when no request scope has set the contextvar.
# In practice every request should call :func:`session_scope` before
# delegating to the agent, but the fallback keeps single-process demos
# from crashing if a caller forgets.
_DEFAULT_SESSION = "__unscoped__"

# Public contextvar — exposed so request handlers, the @Tool methods
# this example ships, and any future middleware can read or set it.
# Treat it as the "current session_id" for the active request.
current_session: ContextVar[str] = ContextVar(
    "memory_assistant.current_session",
    default=_DEFAULT_SESSION,
)


@contextmanager
def session_scope(session_id: str) -> Generator[None]:
    """Bind ``session_id`` to the request's contextvar for the block.

    Usage::

        with session_scope(body.session_id):
            async for chunk in agent.stream(body.message):
                yield chunk

    The contextvar is :class:`contextvars.ContextVar`, so concurrent
    requests in the same event loop see independent values. The token
    returned by :meth:`ContextVar.set` is reset on exit, restoring the
    parent context (or the module-level default).
    """
    token = current_session.set(session_id)
    try:
        yield
    finally:
        current_session.reset(token)


class SessionScopedMemory(Memory):
    """Wrap a :class:`Memory` backend and override the ``session_id``.

    Every method substitutes the incoming ``session_id`` argument (which
    the agent runtime hardcodes to ``"default"``) with the value carried
    in :data:`current_session`. The inner backend is passed through
    verbatim — :class:`InMemoryMemory`, :class:`RedisMemory`,
    :class:`PostgresMemory`, etc. all compose without modification.
    """

    def __init__(self, inner: Memory) -> None:
        self._inner = inner

    @property
    def inner(self) -> Memory:
        """Expose the wrapped backend for introspection / tests."""
        return self._inner

    @override
    async def get(self, session_id: str) -> list[Message]:
        # The ``session_id`` argument is the agent runtime's hardcoded
        # default; the meaningful value lives in the contextvar.
        del session_id
        return await self._inner.get(current_session.get())

    @override
    async def append(self, session_id: str, message: Message) -> None:
        del session_id
        await self._inner.append(current_session.get(), message)

    @override
    async def clear(self, session_id: str) -> None:
        del session_id
        await self._inner.clear(current_session.get())


__all__ = ["SessionScopedMemory", "current_session", "session_scope"]
