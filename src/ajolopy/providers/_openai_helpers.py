"""Shared helpers for OpenAI-compatible providers.

Both :class:`ajolopy.providers.openai.OpenAIProvider` (native OpenAI) and
:class:`ajolopy.providers.universal_openai.UniversalOpenAIProvider`
(Ollama, Groq, Together, Mistral, DeepSeek, OpenRouter — every API that
speaks the OpenAI wire format) talk to the official ``openai`` Python
SDK and therefore share the same translation logic:

- message conversion to OpenAI's chat-completions shape;
- tool conversion to the ``{"type": "function", ...}`` schema;
- response decoding (including JSON tool-call argument parsing);
- streaming-event decoding (text deltas, tool-call deltas, terminal
  ``finish_reason``).

The logic lives here, behind a small set of pure functions, so the two
providers stay in lock-step without duplicating ~150 lines of wire-shape
plumbing. Provider-specific concerns (error subclasses, model-prefix
allowlists, capability flags) stay in each provider package.
"""

import json
from typing import TYPE_CHECKING, Any, cast

import openai

from ajolopy.providers.types import (
    Chunk,
    ChunkUsage,
    FinishReason,
    Response,
    ToolCall,
    ToolCallDelta,
)

if TYPE_CHECKING:
    import logging

    from ajolopy.providers.types import Message, Tool


# SDK exceptions worth surfacing as a typed provider error so callers
# never see raw httpx / SDK internals leak through. Re-exported as a
# module-level tuple so both providers reference the same set.
RETRIABLE_SDK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIStatusError,
)

# OpenAI emits a richer ``finish_reason`` set than the framework's
# normalised :data:`FinishReason` literal. The known ones map cleanly;
# everything else falls through :func:`map_finish_reason` to ``"stop"``
# with a warning so callers learn about the new value without crashing.
FINISH_REASON_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
}


def map_finish_reason(raw: object, logger: logging.Logger) -> FinishReason:
    """Translate an SDK ``finish_reason`` to the framework's literal."""
    if isinstance(raw, str):
        mapped = FINISH_REASON_MAP.get(raw)
        if mapped is not None:
            return mapped
        logger.warning(
            "OpenAI-compatible SDK emitted an unknown finish_reason=%r; mapping to 'stop'.",
            raw,
        )
    return "stop"


def estimate_tokens(text: str) -> int:
    """Char-based fallback (~4 chars per token, OpenAI's documented rule of thumb)."""
    return max(1, len(text) // 4)


def convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate framework messages to OpenAI's chat-completions shape.

    Unlike Anthropic, OpenAI carries the system prompt as a regular
    ``{"role": "system"}`` entry inside the same ``messages`` array —
    no top-level field. Tool replays are likewise expressed as
    ``{"role": "tool", "tool_call_id": ..., "content": ...}`` entries.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            out.append({"role": "system", "content": msg.content})
        elif msg.role == "user":
            out.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            assistant: dict[str, Any] = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in msg.tool_calls
                ]
            out.append(assistant)
        elif msg.role == "tool":
            tool_entry: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content,
            }
            # OpenAI does not have a dedicated "is_error" field on tool
            # results; convention is to leave the flag to the model. The
            # framework still threads it through so providers that do
            # (Anthropic) can use it.
            out.append(tool_entry)
    return out


def convert_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    """Translate framework tools to OpenAI's function-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def convert_response(raw: Any, logger: logging.Logger) -> Response:
    """Decode an OpenAI ``ChatCompletion`` into the framework's ``Response``.

    Defensive accessors so the converter tolerates mocks shaped as
    ``SimpleNamespace`` as well as the real Pydantic models. Tool-call
    arguments are decoded eagerly from their JSON-encoded string into a
    ``dict[str, Any]``; malformed payloads are captured under
    ``{"_raw": <string>}`` plus a warning so the conversation history
    stays consistent and the model can recover on its own.
    """
    choices = cast("list[Any]", getattr(raw, "choices", None) or [])
    first: Any = choices[0] if choices else None
    message: Any = getattr(first, "message", None)
    finish_reason_raw: Any = getattr(first, "finish_reason", None)

    text: str = ""
    if message is not None:
        content = cast("Any", getattr(message, "content", None))
        if isinstance(content, str):
            text = content

    tool_calls: list[ToolCall] = []
    raw_tool_calls: list[Any] = (
        cast("list[Any]", getattr(message, "tool_calls", None) or []) if message is not None else []
    )
    for call in raw_tool_calls:
        function: Any = getattr(call, "function", None)
        name = getattr(function, "name", "") if function is not None else ""
        arguments_raw = getattr(function, "arguments", "") if function is not None else ""
        try:
            arguments: dict[str, Any] = json.loads(arguments_raw) if arguments_raw else {}
        except json.JSONDecodeError:
            logger.warning(
                "OpenAI tool_call %r had non-JSON arguments=%r; passing raw under '_raw'.",
                getattr(call, "id", ""),
                arguments_raw,
            )
            arguments = {"_raw": arguments_raw}
        tool_calls.append(
            ToolCall(
                id=str(getattr(call, "id", "") or ""),
                name=str(name or ""),
                arguments=arguments,
            )
        )

    usage: Any = getattr(raw, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
    # OpenAI exposes prompt-cache reads under ``usage.prompt_tokens_details``.
    # Cache *writes* are billed at the same rate as regular input tokens, so
    # only the read tier is split out — keep ``cache_creation_input_tokens``
    # at 0 for OpenAI / OpenAI-compatible payloads.
    prompt_details: Any = getattr(usage, "prompt_tokens_details", None)
    cache_read = int(getattr(prompt_details, "cached_tokens", 0) or 0)

    finish_reason: FinishReason
    if tool_calls and not isinstance(finish_reason_raw, str):
        finish_reason = "tool_calls"
    else:
        finish_reason = map_finish_reason(finish_reason_raw, logger)

    return Response(
        text=text,
        tool_calls=tool_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        finish_reason=finish_reason,
        cache_read_input_tokens=cache_read,
    )


def convert_stream_event(event: Any, logger: logging.Logger) -> list[Chunk]:
    """Map a single ``ChatCompletionChunk`` to wire-level chunks.

    OpenAI's streaming API emits one ``ChatCompletionChunk`` per server
    push. Each chunk's first choice carries a ``delta`` plus optional
    ``finish_reason``. A single SDK chunk can carry *both* a text delta
    and one or more tool-call deltas, so this helper may return more
    than one wire-level :class:`Chunk`.

    When the request was made with ``stream_options={"include_usage": True}``
    the server emits a final ``ChatCompletionChunk`` with **empty choices**
    and a populated ``usage`` field. That trailing chunk is converted to a
    single wire-level :class:`Chunk` with ``delta=""`` and
    :attr:`Chunk.usage` populated, so the runtime can read it off the
    iterator and attach the values to its ``chat`` span.
    """
    choices = cast("list[Any]", getattr(event, "choices", None) or [])
    if not choices:
        usage = getattr(event, "usage", None)
        if usage is not None:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            # OpenAI's terminal usage chunk carries the same
            # ``prompt_tokens_details.cached_tokens`` field as the
            # non-streaming response. Universal-OpenAI servers that omit
            # it (Ollama, llama.cpp) leave the value at 0 gracefully.
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            cache_read = int(getattr(prompt_details, "cached_tokens", 0) or 0)
            if prompt_tokens > 0 or completion_tokens > 0:
                return [
                    Chunk(
                        delta="",
                        usage=ChunkUsage(
                            input_tokens=prompt_tokens,
                            output_tokens=completion_tokens,
                            cache_read_input_tokens=cache_read,
                        ),
                    )
                ]
        return []
    first: Any = choices[0]
    delta: Any = getattr(first, "delta", None)
    finish_reason_raw: Any = getattr(first, "finish_reason", None)

    emitted: list[Chunk] = []

    text_delta = getattr(delta, "content", None) if delta is not None else None
    if isinstance(text_delta, str) and text_delta:
        emitted.append(Chunk(delta=text_delta))

    tool_call_deltas: list[Any] = (
        cast("list[Any]", getattr(delta, "tool_calls", None) or []) if delta is not None else []
    )
    for tc_delta in tool_call_deltas:
        index_raw = getattr(tc_delta, "index", None)
        index = int(index_raw) if isinstance(index_raw, int) else None
        tc_id_raw = getattr(tc_delta, "id", None)
        tc_id = str(tc_id_raw) if isinstance(tc_id_raw, str) else ""
        function = getattr(tc_delta, "function", None)
        name_raw = getattr(function, "name", None) if function is not None else None
        name = name_raw if isinstance(name_raw, str) else None
        args_raw = getattr(function, "arguments", None) if function is not None else None
        args_delta = args_raw if isinstance(args_raw, str) else None
        emitted.append(
            Chunk(
                delta="",
                tool_call_delta=ToolCallDelta(
                    id=tc_id,
                    name=name,
                    arguments_delta=args_delta,
                    index=index,
                ),
            )
        )

    if finish_reason_raw is not None:
        emitted.append(
            Chunk(
                delta="",
                finish_reason=map_finish_reason(finish_reason_raw, logger),
            )
        )

    return emitted


__all__ = [
    "FINISH_REASON_MAP",
    "RETRIABLE_SDK_EXCEPTIONS",
    "convert_messages",
    "convert_response",
    "convert_stream_event",
    "convert_tools",
    "estimate_tokens",
    "map_finish_reason",
]
