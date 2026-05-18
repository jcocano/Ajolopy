"""Provider abstraction layer.

Public surface:

- ``LLMProvider`` — the abstract base class every concrete provider implements.
- ``register_provider`` / ``get_provider_class`` — registry primitives.
- ``register_route`` / ``resolve_provider`` — model-string-to-provider routing.
- ``Message`` / ``Tool`` / ``ToolCall`` / ``ToolCallDelta`` / ``Response`` /
  ``Chunk`` — wire-format types.
- ``Role`` / ``FinishReason`` — type aliases used by the wire types.
- ``ProviderNotRegisteredError`` / ``UnknownModelError`` — registry errors.

Concrete providers (Anthropic, OpenAI, Gemini, the universal OpenAI-compatible
adapter) live in sibling packages and register themselves via
``register_provider`` at import time. We import them eagerly here so that a
top-level ``import ajolopy`` populates the registry without forcing users to
remember a second import — without this, ``@Agent(model="claude-...")`` would
crash at boot with ``ProviderNotRegisteredError`` on a fresh install (AJ-80).
Their underlying SDKs (``anthropic``, ``openai``, ``google-genai``) are
declared as runtime dependencies in ``pyproject.toml``, so eager import does
not break the install footprint. The ``mcp`` consumer provider stays lazy
because it sits behind an optional extra.
"""

# The four ``from . import <provider> as _<provider>`` lines below look unused
# but are load-bearing: each provider package calls ``register_provider`` at
# import time, and dropping any of them re-introduces the empty-registry crash
# on a fresh ``import ajolopy`` (AJ-80). See the module docstring above.
from . import anthropic as _anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]
from . import gemini as _gemini  # noqa: F401  # pyright: ignore[reportUnusedImport]
from . import openai as _openai  # noqa: F401  # pyright: ignore[reportUnusedImport]
from . import (
    universal_openai as _universal_openai,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .base import LLMProvider, LLMProviderError
from .registry import (
    ProviderNotRegisteredError,
    UnknownModelError,
    get_provider_class,
    register_provider,
    register_route,
    resolve_provider,
)
from .types import (
    Chunk,
    ChunkUsage,
    FinishReason,
    Message,
    Response,
    Role,
    Tool,
    ToolCall,
    ToolCallDelta,
)

__all__ = [
    "Chunk",
    "ChunkUsage",
    "FinishReason",
    "LLMProvider",
    "LLMProviderError",
    "Message",
    "ProviderNotRegisteredError",
    "Response",
    "Role",
    "Tool",
    "ToolCall",
    "ToolCallDelta",
    "UnknownModelError",
    "get_provider_class",
    "register_provider",
    "register_route",
    "resolve_provider",
]
