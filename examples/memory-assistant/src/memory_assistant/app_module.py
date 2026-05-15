"""Root ``@Module`` for the memory-assistant example.

A single ``Tracker`` agent is wired under ``/chat``. The Redis-backed
``@Agent(memory=...)`` ergonomics are the whole point of the example,
so the wiring stays intentionally minimal — no env-driven mode toggle,
no second agent — to keep the reader focused on the memory layer.
"""

from ajolopy import Module
from memory_assistant.agents.tracker import Tracker


@Module(agents=[Tracker])
class AppModule:
    """One agent, one ``@Stream("/chat")`` endpoint, persistent memory."""


__all__ = ["AppModule"]
