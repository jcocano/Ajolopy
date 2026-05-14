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
    ``index`` is the provider-side block index, used to correlate the
    initial ``content_block_start`` (which carries ``id`` and ``name``) with
    subsequent ``content_block_delta`` events (which carry argument
    fragments). When ``index`` is ``None`` the caller must rely on ``id``.
    """

    id: str
    name: str | None = None
    arguments_delta: str | None = None
    index: int | None = None


@dataclass(slots=True)
class Message:
    """A single message in a chat-style conversation.

    ``tool_calls`` is only meaningful on ``assistant`` messages: it carries
    the tool invocations the model produced in the previous turn so the
    next provider call can replay the full conversation history (system →
    user → assistant(tool_use) → tool(tool_result) → assistant). Providers
    that do not support tool use ignore the field.

    ``tool_call_id`` is only meaningful on ``tool`` messages: it links a
    ``tool_result`` back to the originating ``ToolCall.id``. ``is_error``
    on a ``tool`` message signals that the tool execution failed and the
    ``content`` carries the error description — providers forward it as
    an error-flagged tool_result so the model can recover.
    """

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list[ToolCall])
    is_error: bool = False


@dataclass(slots=True)
class Response:
    """A non-streaming completion result.

    ``cache_creation_input_tokens`` / ``cache_read_input_tokens`` carry the
    Anthropic-style cache-tier split when the provider reports it. Defaults
    are 0 so providers that do not report cache details (or backends that
    do not bill them separately) leave the fields harmlessly empty — the
    pricing layer simply contributes 0 to the cache tiers in that case.
    """

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list[ToolCall])
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: FinishReason = "stop"
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(slots=True)
class ChunkUsage:
    """Token usage reported alongside the terminal chunk of a stream.

    Providers populate this on the **last** ``Chunk`` they yield, sourcing
    the numbers from the underlying SDK's terminal usage event (Anthropic's
    ``message_delta``, OpenAI's ``include_usage`` chunk, Gemini's
    ``usage_metadata``). Intermediate chunks leave ``Chunk.usage`` as
    ``None``. When the upstream server does not include usage at all
    (some OpenAI-compatible deployments), the terminal chunk's ``usage``
    also stays ``None`` and consumers must tolerate that.

    ``cache_creation_input_tokens`` / ``cache_read_input_tokens`` mirror
    the cache-tier split on :class:`Response`. Defaults are 0 for the same
    backward-compatibility reason: providers that do not surface the split
    (OpenAI streams the ``prompt_tokens_details.cached_tokens`` value into
    ``cache_read_input_tokens``; Ollama and similar leave both at 0).
    """

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(slots=True)
class Chunk:
    """A single delta emitted while streaming."""

    delta: str
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: FinishReason | None = None
    usage: ChunkUsage | None = None
