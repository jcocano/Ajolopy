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
``register_provider`` at import time.
"""

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
