"""Runnable companion to the Ajolopy memory reference (AJ-64).

The package shows ``@Agent(memory="redis://...")`` end-to-end: a tiny
personal task tracker that persists every turn to Redis and partitions
its history by ``session_id``.

- :mod:`memory_assistant.memory` — :class:`SessionScopedMemory`, the
  escape-hatch :class:`ajolopy.memory.Memory` wrapper that remaps the
  agent runtime's hardcoded ``"default"`` session_id to a per-request
  :class:`contextvars.ContextVar` value.
- :mod:`memory_assistant.agents.tracker` — the ``Tracker`` ``@Agent``,
  its ``record_task`` ``@Tool``, and its ``@Stream("/chat")`` endpoint.
- :mod:`memory_assistant.app_module` — root ``@Module`` wiring.
- :mod:`memory_assistant.main` — ASGI entry point used by ``ajolopy dev``.
"""

# Side-effect import — registers ``AnthropicProvider`` under the
# ``"anthropic"`` routing key so ``@Agent(model="claude-...")`` can
# resolve at decoration time without raising
# ``ProviderNotRegisteredError``. See
# ``ajolopy/providers/anthropic/__init__.py``.
import ajolopy.providers.anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

__all__ = ["__version__"]

__version__ = "0.0.1"
