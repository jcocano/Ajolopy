"""Step 1 — the persistent ``Tracker`` agent.

A tiny personal task tracker. The agent's *memory* is the conversation
transcript, which is persisted to Redis via the magical
``memory="redis://..."`` URL kwarg. The ``record_task`` tool keeps the
running list in process, partitioned by the same ``session_id`` the
memory wrapper uses, so the agent has a deterministic counter to quote
back to the user.

Drift note — observability:
    OpenTelemetry instrumentation is always on in v0.1 (no ``trace=``
    kwarg on ``@Agent``). Spans are cheap no-ops without the
    ``ajolopy[otel]`` extra installed.

Drift note — session_id:
    ``AgentRuntime`` v0.1 hardcodes ``session_id == "default"`` when it
    calls into the memory backend. The :class:`SessionScopedMemory`
    wrapper bridges that by reading a :class:`contextvars.ContextVar`
    set by :func:`session_scope` inside the ``@Stream`` handler. That is
    the canonical "escape hatch" for the magical URL default — see
    :mod:`memory_assistant.memory` for the wrapper.
"""

import os
from collections import defaultdict

# NOTE: ``AsyncGenerator`` MUST be imported at runtime (not under
# ``if TYPE_CHECKING:``). Python 3.14 + PEP 649 defers annotation
# evaluation until something calls ``get_annotations()`` /
# ``inspect.signature()``; the framework's ``@Stream`` mount path does
# exactly that on the ``respond`` handler below to wire up the route.
# If this symbol is only visible to static analysers, the mount step
# explodes with ``NameError: name 'AsyncGenerator' is not defined`` at
# server boot — a regression that first surfaced post-AJ-87.
from collections.abc import AsyncGenerator  # noqa: TC003
from typing import Annotated

from pydantic import BaseModel, Field

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body
from ajolopy.memory import resolve_memory
from memory_assistant.memory import (
    SessionScopedMemory,
    current_session,
    session_scope,
)


def _build_memory() -> SessionScopedMemory | None:
    """Resolve the ``REDIS_URL`` env var into a :class:`Memory` instance.

    The resolver picks the backend by URL scheme:

    - ``redis://...``   → :class:`ajolopy.memory.RedisMemory`
    - ``memory://``     → :class:`ajolopy.memory.InMemoryMemory` (tests)

    The wrapper layer is what makes ``session_id`` partitioning work in
    a v0.1 ``AgentRuntime``.
    """
    inner = resolve_memory(os.environ.get("REDIS_URL", "memory://"))
    if inner is None:
        return None
    return SessionScopedMemory(inner)


# Per-session in-process registry that ``record_task`` mutates. The chat
# transcript itself lives in Redis (the memory layer); this is just the
# deterministic counter the tool returns to the LLM so the assistant can
# answer "how many tasks do I have open?" without re-reading the whole
# transcript.
_TASKS_BY_SESSION: dict[str, list[str]] = defaultdict(list)


class ChatRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint.

    ``session_id`` is required — it is the partition key the memory
    wrapper uses to keep one user's tasks isolated from another's. The
    field is unconstrained string for the example; a production app
    would gate it against an auth token.
    """

    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


@Agent(
    model="claude-opus-4-7",
    system=(
        "You are a personal task tracker. "
        "When the user asks you to add a task, call the record_task tool. "
        "When the user asks how many tasks they have, quote the count "
        "from the tool's most recent reply. Be concise and friendly."
    ),
    memory=_build_memory(),
    fallback="claude-haiku-4-5",
)
class Tracker:
    """The personal task-tracking assistant."""

    @Tool
    async def record_task(self, description: str) -> dict[str, object]:
        """Record a new task under the active session and return the count.

        ``description`` is the human-readable task; the assistant chooses
        the wording from the user's message. Returns a dict with the
        new task and the updated total so the model can quote either.
        """
        session = current_session.get()
        tasks = _TASKS_BY_SESSION[session]
        tasks.append(description)
        return {
            "session_id": session,
            "added": description,
            "open_tasks": len(tasks),
        }

    @Stream("/chat")
    async def respond(
        self,
        body: Annotated[ChatRequest, Body()],
    ) -> AsyncGenerator[str]:
        """Stream a reply for the user's message over SSE.

        The handler binds ``body.session_id`` to the request-scoped
        :class:`contextvars.ContextVar` before delegating to
        ``self.stream``. Everything inside that ``with`` block — the
        agent runtime's memory calls **and** the ``record_task`` tool
        — sees the same session_id.
        """
        # ``self.stream`` is injected by ``@Agent`` at decoration time;
        # static analysers cannot see the attribute, so silence the
        # missing-attribute warning here. Same pattern as the framework's
        # own composability tests.
        with session_scope(body.session_id):
            async for chunk in self.stream(body.message):  # type: ignore[attr-defined]
                yield chunk


__all__ = ["ChatRequest", "Tracker"]
