"""``AnthropicProvider`` — concrete ``LLMProvider`` over the Anthropic SDK.

Bridges the framework's provider-agnostic wire types to Anthropic's native
Messages API. The implementation deliberately keeps the surface narrow:
features that need framework-wide buy-in (extended thinking, vision, PDFs)
are deferred until they land as separate board items.
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, cast, override

import anthropic

from ajolopy.providers.base import LLMProvider
from ajolopy.providers.types import (
    Chunk,
    ChunkUsage,
    FinishReason,
    Message,
    Response,
    Tool,
    ToolCall,
    ToolCallDelta,
)

from .errors import (
    AnthropicConfigError,
    AnthropicEmbeddingsNotSupportedError,
    AnthropicProviderError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_LOGGER = logging.getLogger(__name__)

# Default cap when callers do not pass max_tokens. The Anthropic API requires
# the field; 1024 keeps the demo responsive without being so high that a bad
# test hits the rate limit.
_DEFAULT_MAX_TOKENS = 1024

# SDK exceptions that are worth surfacing as our typed AnthropicProviderError
# so callers never see raw httpx / SDK internals.
_RETRIABLE_SDK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIStatusError,
)

_STOP_REASON_MAP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def _map_stop_reason(raw: object) -> FinishReason:
    if isinstance(raw, str) and raw in _STOP_REASON_MAP:
        return _STOP_REASON_MAP[raw]
    return "stop"


def _track_stream_usage(
    event: Any,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
) -> tuple[int, int, int, int]:
    """Pull running input/output/cache token counts from Anthropic stream events.

    Anthropic emits ``message_start`` with the prompt's ``input_tokens`` and
    an initial ``output_tokens`` of zero, then increments ``output_tokens``
    on each ``message_delta``. The terminal ``message_delta`` (with
    ``stop_reason``) carries the final ``output_tokens``. Cache-tier counts
    (``cache_creation_input_tokens`` / ``cache_read_input_tokens``) ride on
    the same ``message.usage`` payload. This helper accepts any event and
    returns the latest running totals so the caller can attach the final
    quadruple to the terminal chunk.
    """
    event_type = getattr(event, "type", None)
    if event_type == "message_start":
        message = getattr(event, "message", None)
        usage = getattr(message, "usage", None)
        if usage is not None:
            input_tokens = int(getattr(usage, "input_tokens", input_tokens) or input_tokens)
            output_tokens = int(getattr(usage, "output_tokens", output_tokens) or output_tokens)
            cache_creation_input_tokens = int(
                getattr(usage, "cache_creation_input_tokens", cache_creation_input_tokens)
                or cache_creation_input_tokens
            )
            cache_read_input_tokens = int(
                getattr(usage, "cache_read_input_tokens", cache_read_input_tokens)
                or cache_read_input_tokens
            )
    elif event_type == "message_delta":
        usage = getattr(event, "usage", None)
        if usage is not None:
            # Anthropic only re-emits the keys that changed; fall back to the
            # current running value when a key is absent.
            new_input = getattr(usage, "input_tokens", None)
            new_output = getattr(usage, "output_tokens", None)
            new_cache_create = getattr(usage, "cache_creation_input_tokens", None)
            new_cache_read = getattr(usage, "cache_read_input_tokens", None)
            if new_input is not None:
                input_tokens = int(new_input or input_tokens)
            if new_output is not None:
                output_tokens = int(new_output or output_tokens)
            if new_cache_create is not None:
                cache_creation_input_tokens = int(new_cache_create or cache_creation_input_tokens)
            if new_cache_read is not None:
                cache_read_input_tokens = int(new_cache_read or cache_read_input_tokens)
    return input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens


def _estimate_tokens(text: str) -> int:
    """Char-based fallback (~4 chars per token, matches OpenAI's rule of thumb)."""
    return max(1, len(text) // 4)


class AnthropicProvider(LLMProvider):
    """``LLMProvider`` backed by the official ``anthropic`` Python SDK.

    Construct one of three ways:

    - ``AnthropicProvider()`` — reads ``ANTHROPIC_API_KEY`` from the env.
    - ``AnthropicProvider(api_key=...)`` — explicit key, used by the
      framework bootstrap (AJ-14) when it forwards the value from
      ``ConfigService``.
    - ``AnthropicProvider(client=...)`` — pre-built ``AsyncAnthropic`` for
      callers that need a custom timeout, proxy, base_url, or retry policy.
    """

    GEN_AI_SYSTEM = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return
        if api_key is not None:
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
            return
        # Fall back to env var. AsyncAnthropic does read it itself but its
        # error message surfaces only on the first request; check up front
        # so bootstrap fails before a single call is made.
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise AnthropicConfigError(
                "ANTHROPIC_API_KEY missing. Pass api_key=, client=, or set the env var."
            )
        self._client = anthropic.AsyncAnthropic()

    @property
    def client(self) -> anthropic.AsyncAnthropic:
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
        self._ensure_claude_model(model)
        system_param, claude_messages = self._split_system(messages, cache=cache)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS,
        }
        if system_param is not None:
            kwargs["system"] = system_param
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            raw = cast("Any", await self._client.messages.create(**kwargs))
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            raise AnthropicProviderError(f"Anthropic SDK error during complete(): {exc}") from exc

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
        # Build kwargs eagerly so configuration errors raise before any
        # generator is even created.
        self._ensure_claude_model(model)
        system_param, claude_messages = self._split_system(messages, cache=cache)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS,
        }
        if system_param is not None:
            kwargs["system"] = system_param
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature

        async def _generator() -> AsyncIterator[Chunk]:
            # Anthropic streams usage in two events: ``message_start`` carries
            # the prompt's input_tokens, and each ``message_delta`` updates
            # ``output_tokens`` (final values land on the message_delta that
            # also carries ``stop_reason``). Cache-tier counts (cache_creation
            # / cache_read) ride on the same usage payload, so we accumulate
            # all four and attach them to the terminal chunk for the runtime
            # to populate ``gen_ai.usage.*`` plus ``gen_ai.cost_usd.*``.
            input_tokens = 0
            output_tokens = 0
            cache_creation_input_tokens = 0
            cache_read_input_tokens = 0
            try:
                async with self._client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        (
                            input_tokens,
                            output_tokens,
                            cache_creation_input_tokens,
                            cache_read_input_tokens,
                        ) = _track_stream_usage(
                            event,
                            input_tokens,
                            output_tokens,
                            cache_creation_input_tokens,
                            cache_read_input_tokens,
                        )
                        chunk = self._convert_stream_event(event)
                        if chunk is None:
                            continue
                        if chunk.finish_reason is not None and (
                            input_tokens > 0
                            or output_tokens > 0
                            or cache_creation_input_tokens > 0
                            or cache_read_input_tokens > 0
                        ):
                            chunk = Chunk(
                                delta=chunk.delta,
                                tool_call_delta=chunk.tool_call_delta,
                                finish_reason=chunk.finish_reason,
                                usage=ChunkUsage(
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    cache_creation_input_tokens=cache_creation_input_tokens,
                                    cache_read_input_tokens=cache_read_input_tokens,
                                ),
                            )
                        yield chunk
            except _RETRIABLE_SDK_EXCEPTIONS as exc:
                raise AnthropicProviderError(f"Anthropic SDK error during stream(): {exc}") from exc

        return _generator()

    @override
    async def embed(
        self,
        *,
        model: str,
        text: str | list[str],
    ) -> list[list[float]]:
        raise AnthropicEmbeddingsNotSupportedError(
            "Anthropic does not provide native text embeddings. "
            "Route embeddings through a different provider, "
            "e.g. OpenAI's `text-embedding-3-small` or `-large`."
        )

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        # The SDK ships an async count_tokens endpoint. We only call it when
        # we are NOT already inside an event loop — otherwise we cannot
        # synchronously wait, and falling back to the char estimate is the
        # right thing to do (the framework will be running async anyway, so
        # this method is only useful from sync entrypoints like CLIs).
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if not in_loop:
            try:
                result = asyncio.run(
                    self._client.messages.count_tokens(
                        model=model,
                        messages=[{"role": "user", "content": text}],
                    )
                )
                return int(result.input_tokens)
            except Exception as exc:
                _LOGGER.warning(
                    "Anthropic count_tokens failed (%s); falling back to estimate.",
                    exc,
                )

        return _estimate_tokens(text)

    @override
    def supports_prompt_caching(self) -> bool:
        return True

    @override
    def supports_tool_calling(self) -> bool:
        return True

    @override
    async def health_check(self) -> None:
        """Reach the Anthropic API with the cheapest call available.

        Uses ``models.list(limit=1)`` because it requires only a valid
        API key and does not bill tokens. Translates SDK exceptions to
        :class:`AnthropicProviderError` so the doctor renderer never
        sees raw ``httpx`` / SDK internals.
        """
        try:
            await self._client.models.list(limit=1)
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            raise AnthropicProviderError(
                f"Anthropic SDK error during health_check(): {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_claude_model(model: str) -> None:
        if not model.startswith("claude-"):
            raise AnthropicProviderError(
                f"AnthropicProvider only supports claude-* models, got {model!r}. "
                f"Check the registry routing or pass a Claude model."
            )

    @staticmethod
    def _split_system(
        messages: list[Message], *, cache: bool
    ) -> tuple[str | list[dict[str, Any]] | None, list[dict[str, Any]]]:
        """Extract system messages and convert the chat messages to SDK shape.

        Anthropic's API takes the system prompt as a top-level ``system``
        parameter (string or list of content blocks), with the rest of the
        conversation in ``messages``. When ``cache=True`` the system prompt
        is forwarded as a content-block list with ``cache_control`` set so
        prompt caching kicks in.
        """
        system_blocks: list[dict[str, Any]] = []
        chat_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                block: dict[str, Any] = {"type": "text", "text": msg.content}
                if cache:
                    block["cache_control"] = {"type": "ephemeral"}
                system_blocks.append(block)
            elif msg.role == "user":
                chat_messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                if msg.tool_calls:
                    blocks: list[dict[str, Any]] = []
                    if msg.content:
                        blocks.append({"type": "text", "text": msg.content})
                    for call in msg.tool_calls:
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": call.id,
                                "name": call.name,
                                "input": call.arguments,
                            }
                        )
                    chat_messages.append({"role": "assistant", "content": blocks})
                else:
                    chat_messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool":
                tool_result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }
                if msg.is_error:
                    tool_result["is_error"] = True
                chat_messages.append({"role": "user", "content": [tool_result]})

        if not system_blocks:
            return None, chat_messages
        if cache:
            # Keep the block list shape so cache_control survives.
            return system_blocks, chat_messages
        # No cache → collapse to a single string for the simple path.
        return "\n\n".join(block["text"] for block in system_blocks), chat_messages

    @staticmethod
    def _convert_tools(tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    @staticmethod
    def _convert_response(raw: Any) -> Response:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in raw.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(block.text)
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        usage = getattr(raw, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)

        return Response(
            text="".join(text_parts),
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            finish_reason=_map_stop_reason(getattr(raw, "stop_reason", None)),
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        )

    @staticmethod
    def _convert_stream_event(event: Any) -> Chunk | None:
        """Map an SDK stream event to a wire-level Chunk.

        Returns ``None`` for events that do not map to a chunk (e.g. start
        markers); the generator skips them silently.
        """
        event_type = getattr(event, "type", None)

        if event_type == "content_block_delta":
            delta = getattr(event, "delta", None)
            delta_type = getattr(delta, "type", None) if delta is not None else None
            if delta_type == "text_delta":
                return Chunk(delta=getattr(delta, "text", ""))
            if delta_type == "input_json_delta":
                index_raw = getattr(event, "index", None)
                index = int(index_raw) if isinstance(index_raw, int) else None
                return Chunk(
                    delta="",
                    tool_call_delta=ToolCallDelta(
                        id="",
                        arguments_delta=getattr(delta, "partial_json", ""),
                        index=index,
                    ),
                )
            return None

        if event_type == "content_block_start":
            block = getattr(event, "content_block", None)
            if getattr(block, "type", None) == "tool_use":
                index_raw = getattr(event, "index", None)
                index = int(index_raw) if isinstance(index_raw, int) else None
                return Chunk(
                    delta="",
                    tool_call_delta=ToolCallDelta(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", None),
                        index=index,
                    ),
                )
            return None

        if event_type == "message_delta":
            delta = getattr(event, "delta", None)
            stop_reason = getattr(delta, "stop_reason", None) if delta is not None else None
            if stop_reason is not None:
                return Chunk(delta="", finish_reason=_map_stop_reason(stop_reason))
            return None

        return None
