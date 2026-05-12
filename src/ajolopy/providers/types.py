"""Wire-format types shared by every LLMProvider implementation.

These types are deliberately provider-agnostic. Concrete providers translate
to and from their SDK's native shapes (Anthropic Messages, OpenAI ChatCompletion,
Gemini GenerateContent) at the boundary.

Implemented as plain ``@dataclass`` rather than Pydantic models so the provider
layer takes no external runtime dependency. Validation lives at the framework
boundary (e.g. ``@Agent`` argument validation), not here.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
"""LLM message author. Mirrors the OpenAI/Anthropic chat conventions."""

FinishReason = Literal["stop", "length", "tool_calls", "error"]
"""Why the model stopped generating. Providers normalise their native reasons
into one of these four values."""


@dataclass(slots=True)
class Message:
    """A single message in a chat-style conversation."""

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(slots=True)
class Tool:
    """A tool offered to the model. ``parameters`` is JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    """A fully materialised tool invocation produced by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ToolCallDelta:
    """Incremental tool-call payload yielded while streaming.

    ``arguments_delta`` is a partial JSON fragment — the caller concatenates
    fragments and parses once ``finish_reason`` is set on the parent chunk.
    """

    id: str
    name: str | None = None
    arguments_delta: str | None = None


@dataclass(slots=True)
class Response:
    """A non-streaming completion result."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list[ToolCall])
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: FinishReason = "stop"


@dataclass(slots=True)
class Chunk:
    """A single delta emitted while streaming."""

    delta: str
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: FinishReason | None = None
