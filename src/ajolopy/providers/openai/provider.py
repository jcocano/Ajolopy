"""``OpenAIProvider`` — concrete ``LLMProvider`` over the OpenAI SDK.

Bridges the framework's provider-agnostic wire types to OpenAI's native
Chat Completions API. The implementation deliberately keeps the surface
narrow: features that need framework-wide buy-in (reasoning-effort knobs
for ``o1``/``o3``, structured outputs with ``response_format``, vision,
audio) are deferred until they land as separate board items.
"""

import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast, override

import openai

from ajolopy.providers.base import LLMProvider
from ajolopy.providers.types import (
    Chunk,
    FinishReason,
    Message,
    Response,
    Tool,
    ToolCall,
    ToolCallDelta,
)

from .errors import OpenAIConfigError, OpenAIProviderError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_LOGGER = logging.getLogger(__name__)

# SDK exceptions worth surfacing as a typed OpenAIProviderError so callers
# never see raw httpx / SDK internals leak through.
_RETRIABLE_SDK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIStatusError,
)

# OpenAI emits a richer finish_reason set than the framework's normalised
# FinishReason literal. The known ones map cleanly; everything else falls
# through ``_map_finish_reason`` to ``"stop"`` with a warning.
_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
}

# Model-string prefixes accepted by this provider. Defence-in-depth so a
# misrouted call from a subclass or a misconfigured registry fails loudly
# instead of confusing the SDK with a model it cannot recognise.
_OPENAI_MODEL_PREFIXES: tuple[str, ...] = (
    "gpt-",
    "o1-",
    "o3-",
    "text-embedding-",
    "chatgpt-",
)


def _map_finish_reason(raw: object) -> FinishReason:
    if isinstance(raw, str):
        mapped = _FINISH_REASON_MAP.get(raw)
        if mapped is not None:
            return mapped
        _LOGGER.warning(
            "OpenAI emitted an unknown finish_reason=%r; mapping to 'stop'.",
            raw,
        )
    return "stop"


def _estimate_tokens(text: str) -> int:
    """Char-based fallback (~4 chars per token, OpenAI's documented rule of thumb)."""
    return max(1, len(text) // 4)


class OpenAIProvider(LLMProvider):
    """``LLMProvider`` backed by the official ``openai`` Python SDK.

    Construct one of three ways:

    - ``OpenAIProvider()`` — reads ``OPENAI_API_KEY`` from the env.
    - ``OpenAIProvider(api_key=...)`` — explicit key, used by the framework
      bootstrap (AJ-14) when it forwards the value from ``ConfigService``.
    - ``OpenAIProvider(client=...)`` — pre-built ``AsyncOpenAI`` for callers
      that need a custom timeout, proxy, base_url (e.g. Azure OpenAI's
      tenant URL), or retry policy.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return
        if api_key is not None:
            self._client = openai.AsyncOpenAI(api_key=api_key)
            return
        # Fall back to env var. AsyncOpenAI reads it itself but its error
        # surfaces only on the first request; check up front so bootstrap
        # fails before a single call is made.
        if not os.environ.get("OPENAI_API_KEY"):
            raise OpenAIConfigError(
                "OPENAI_API_KEY missing. Pass api_key=, client=, or set the env var."
            )
        self._client = openai.AsyncOpenAI()

    @property
    def client(self) -> openai.AsyncOpenAI:
        """Expose the underlying SDK client for the escape-hatch case."""
        return self._client

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        # OpenAI caches automatically once the prompt crosses the SDK's
        # documented threshold (~1024 tokens); ``cache=True`` is intentionally
        # a no-op so the SDK call stays identical between cache=True and
        # cache=False. The capability flag still reports True.
        _ = cache
        self._ensure_openai_model(model)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            raw = cast("Any", await self._client.chat.completions.create(**kwargs))
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            raise OpenAIProviderError(f"OpenAI SDK error during complete(): {exc}") from exc

        return self._convert_response(raw)

    @override
    def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:
        # Cache flag is a no-op — see ``complete()`` for the rationale.
        _ = cache
        self._ensure_openai_model(model)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        async def _generator() -> AsyncIterator[Chunk]:
            sdk_stream: Any = None
            try:
                sdk_stream = cast("Any", await self._client.chat.completions.create(**kwargs))
                async for event in cast("AsyncIterator[Any]", sdk_stream):
                    for chunk in self._convert_stream_event(event):
                        yield chunk
            except _RETRIABLE_SDK_EXCEPTIONS as exc:
                raise OpenAIProviderError(f"OpenAI SDK error during stream(): {exc}") from exc
            finally:
                # Best-effort: cancel the underlying SSE connection on early
                # exit so we do not leak HTTP sockets if the caller breaks
                # out of the iterator or calls aclose().
                close: Any = getattr(sdk_stream, "close", None)
                if callable(close):
                    try:
                        result: Any = close()
                        if hasattr(result, "__await__"):
                            await result
                    except Exception:
                        # Closing is best-effort; never let it mask a real
                        # exception bubbling up from the stream body.
                        _LOGGER.debug("OpenAI stream close() failed", exc_info=True)

        return _generator()

    @override
    async def embed(
        self,
        *,
        model: str,
        text: str | list[str],
    ) -> list[list[float]]:
        self._ensure_openai_model(model)
        # Normalise to a list so the SDK call shape is uniform regardless of
        # whether the caller passed a single string or a batch.
        inputs = [text] if isinstance(text, str) else list(text)
        if not inputs:
            return []
        try:
            raw = cast(
                "Any",
                await self._client.embeddings.create(model=model, input=inputs),
            )
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            raise OpenAIProviderError(f"OpenAI SDK error during embed(): {exc}") from exc

        # ``raw.data`` is a list of ``Embedding`` objects ordered by input
        # index; each has a ``.embedding`` field with the float vector.
        return [list(item.embedding) for item in raw.data]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        try:
            import tiktoken

            encoding = tiktoken.encoding_for_model(model)
            return max(1, len(encoding.encode(text)))
        except Exception as exc:
            _LOGGER.warning(
                "OpenAI count_tokens fell back to char estimate for model=%r (%s).",
                model,
                exc,
            )
            return _estimate_tokens(text)

    @override
    def supports_prompt_caching(self) -> bool:
        return True

    @override
    def supports_tool_calling(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_openai_model(model: str) -> None:
        if not model.startswith(_OPENAI_MODEL_PREFIXES):
            raise OpenAIProviderError(
                f"OpenAIProvider only supports OpenAI-family models "
                f"({', '.join(_OPENAI_MODEL_PREFIXES)}), got {model!r}. "
                f"Check the registry routing or pass a supported model."
            )

    @staticmethod
    def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
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
                # results; convention is to leave the flag to the model.
                # The framework still threads it through so providers that
                # do (Anthropic) can use it.
                out.append(tool_entry)
        return out

    @staticmethod
    def _convert_tools(tools: list[Tool]) -> list[dict[str, Any]]:
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

    @staticmethod
    def _convert_response(raw: Any) -> Response:
        # Defensive accessors so the converter tolerates mocks shaped as
        # SimpleNamespace as well as the real Pydantic models.
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
            cast("list[Any]", getattr(message, "tool_calls", None) or [])
            if message is not None
            else []
        )
        for call in raw_tool_calls:
            function: Any = getattr(call, "function", None)
            name = getattr(function, "name", "") if function is not None else ""
            arguments_raw = getattr(function, "arguments", "") if function is not None else ""
            try:
                arguments: dict[str, Any] = json.loads(arguments_raw) if arguments_raw else {}
            except json.JSONDecodeError:
                _LOGGER.warning(
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

        finish_reason: FinishReason
        if tool_calls and not isinstance(finish_reason_raw, str):
            finish_reason = "tool_calls"
        else:
            finish_reason = _map_finish_reason(finish_reason_raw)

        return Response(
            text=text,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _convert_stream_event(event: Any) -> list[Chunk]:
        """Map a single ``ChatCompletionChunk`` to wire-level chunks.

        OpenAI's streaming API emits one ``ChatCompletionChunk`` per server
        push. Each chunk's first choice carries a ``delta`` plus optional
        ``finish_reason``. A single SDK chunk can carry *both* a text delta
        and one or more tool-call deltas, so this helper may return more
        than one wire-level ``Chunk``.
        """
        choices = cast("list[Any]", getattr(event, "choices", None) or [])
        if not choices:
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
                    finish_reason=_map_finish_reason(finish_reason_raw),
                )
            )

        return emitted
