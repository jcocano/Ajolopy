"""Test-suite preamble for the memory-assistant example.

Sets the env vars the example reads at module-import time **before** any
``memory_assistant.*`` module is collected:

- ``ANTHROPIC_API_KEY`` — a dummy value so the Anthropic provider's
  decoration-time validation passes without a real key.
- ``REDIS_URL`` — pinned to ``memory://`` so :func:`resolve_memory`
  returns :class:`ajolopy.memory.InMemoryMemory` and the smoke test
  never opens a TCP socket to Redis.

No SDK monkeypatching happens here: the smoke test never calls a
provider, so the dummy key is enough for decoration-time validation.
"""

import os

# Both vars are set before any ``memory_assistant.*`` module is imported.
# ``conftest.py`` is evaluated by pytest at collection time, ahead of
# test modules.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy")
os.environ.setdefault("REDIS_URL", "memory://")
