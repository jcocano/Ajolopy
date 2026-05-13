"""``GeminiProvider`` — concrete ``LLMProvider`` over the Google Gen AI SDK.

Bridges the framework's provider-agnostic wire types to Google's native
Gemini API via the official ``google-genai`` Python SDK. The implementation
deliberately keeps the surface narrow: features that need framework-wide
buy-in (multimodal inputs, grounding / Google Search retrieval, Vertex AI
specific knobs, the explicit ``cachedContent`` resource lifecycle) are
deferred until they land as separate board items.

Wire-level conversion helpers (messages, tools, response decoding,
streaming events) live inline in this module rather than in a shared file:
Gemini's SDK shape (``Content`` / ``Part`` trees, ``FunctionCall`` /
``FunctionResponse`` parts, ``UsageMetadata``) is too different from the
OpenAI-compatible providers to share translation logic without ugly
adapters. AJ-22's helpers stay scoped to the OpenAI family.
"""

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast, override

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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

from .errors import GeminiConfigError, GeminiProviderError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_LOGGER = logging.getLogger(__name__)


# Model-string prefixes accepted by this provider. Defence-in-depth so a
# misrouted call from a subclass or a misconfigured registry fails loudly
# instead of confusing the SDK with a model it cannot recognise.
_GEMINI_MODEL_PREFIXES: tuple[str, ...] = (
    "gemini-",
    "text-embedding-",
    "embedding-",
)

# Embed-only prefixes — passing a generation model to ``embed()`` is a
# common copy-paste mistake; surface a typed error instead of letting the
# SDK reject the request with a generic 400.
_GEMINI_EMBEDDING_PREFIXES: tuple[str, ...] = (
    "text-embedding-",
    "embedding-",
)

# SDK exceptions worth surfacing as a typed provider error so callers
# never see raw SDK internals leak through.
_RETRIABLE_SDK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    genai_errors.APIError,
    genai_errors.ClientError,
    genai_errors.ServerError,
    genai_errors.UnknownApiResponseError,
)

# Gemini emits a richer ``FinishReason`` enum than the framework's
# normalised :data:`FinishReason` literal. Map the values we care about
# explicitly; safety / recitation / other map to ``"error"`` so the stream
# terminates cleanly at the iterator boundary (matching AJ-3's
# ``@Stream`` contract). Unknown values fall through to ``"stop"`` with a
# logged warning.
_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
}

_FINISH_REASON_ERROR_VALUES: frozenset[str] = frozenset(
    {
        "SAFETY",
        "RECITATION",
        "OTHER",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "MALFORMED_FUNCTION_CALL",
        "IMAGE_SAFETY",
        "UNEXPECTED_TOOL_CALL",
        "IMAGE_PROHIBITED_CONTENT",
        "NO_IMAGE",
        "IMAGE_RECITATION",
        "IMAGE_OTHER",
        "LANGUAGE",
    }
)


def _finish_reason_to_str(raw: object) -> str | None:
    """Normalise a Gemini finish-reason value to its string form.

    The SDK sometimes returns a :class:`types.FinishReason` enum instance
    and sometimes a plain string (especially in mocks); accept both.
    """
    if raw is None:
        return None
    # Pydantic enums expose ``.value`` (a string) and stringify the enum
    # member name otherwise. SimpleNamespace mocks pass strings directly.
    value = getattr(raw, "value", None)
    if isinstance(value, str):
        return value
    if isinstance(raw, str):
        return raw
    return str(raw)


def _map_finish_reason(raw: object) -> tuple[FinishReason, str | None]:
    """Translate an SDK finish reason to ``(literal, raw_or_none)``.

    The second tuple entry is the raw reason string when it falls into the
    ``"error"`` bucket — callers log it so the underlying refusal is
    discoverable from the test logs without leaking SDK types upward.
    """
    as_str = _finish_reason_to_str(raw)
    if as_str is None:
        return "stop", None
    if as_str in _FINISH_REASON_MAP:
        return _FINISH_REASON_MAP[as_str], None
    if as_str in _FINISH_REASON_ERROR_VALUES:
        return "error", as_str
    return "stop", None


def _estimate_tokens(text: str) -> int:
    """Char-based fallback (~4 chars per token, matches OpenAI's rule of thumb)."""
    return max(1, len(text) // 4)


class GeminiProvider(LLMProvider):
    """``LLMProvider`` backed by the official ``google-genai`` Python SDK.

    Construct one of three ways:

    - ``GeminiProvider()`` — reads ``GEMINI_API_KEY`` from the env (the SDK
      also honours ``GOOGLE_API_KEY`` as a fallback).
    - ``GeminiProvider(api_key=...)`` — explicit key, used by the framework
      bootstrap (AJ-14) when it forwards the value from ``ConfigService``.
    - ``GeminiProvider(client=...)`` — pre-built ``genai.Client`` for callers
      that need a custom timeout, Vertex AI mode, or any other SDK-level
      configuration. The provider does not introspect the client.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return
        if api_key is not None:
            self._client = genai.Client(api_key=api_key)
            return
        # Fall back to env var. ``genai.Client()`` reads it itself but its
        # error surfaces only on the first request; check up front so the
        # framework bootstrap fails before a single call is made.
        if not os.environ.get("GEMINI_API_KEY"):
            raise GeminiConfigError(
                "GEMINI_API_KEY missing — pass api_key=, client=, or set the env var."
            )
        self._client = genai.Client()

    @property
    def client(self) -> genai.Client:
        """Expose the underlying SDK client for the escape-hatch case."""
        return self._client

    @property
    def _aio_models(self) -> Any:
        """Return ``client.aio.models`` cast to ``Any``.

        The SDK signatures on this object carry a sprawling
        ``PartUnionDict`` union that pyright cannot resolve narrowly. We
        cast once here so the rest of the implementation reads cleanly
        and the strict checker stays focused on framework boundaries
        instead of SDK internals.
        """
        return cast("Any", self._client.aio.models)

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
        # Gemini's prompt caching uses a stateful cachedContent resource
        # lifecycle that does not map cleanly onto a stateless ``cache: bool``
        # flag; ``cache=True`` is therefore a documented no-op and
        # ``supports_prompt_caching()`` honestly returns ``False``. The full
        # lifecycle lives in AJ-58. The unused assignment makes the intent
        # explicit to readers and pyright.
        _ = cache
        self._ensure_gemini_model(model)
        system_instruction, contents = self._convert_messages(messages)
        config = self._build_config(
            system_instruction=system_instruction,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        kwargs: dict[str, Any] = {"model": model, "contents": contents}
        if config is not None:
            kwargs["config"] = config

        try:
            raw: Any = await self._aio_models.generate_content(**kwargs)
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            raise GeminiProviderError(f"Gemini SDK error during complete(): {exc}") from exc

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
        # Build kwargs eagerly so configuration errors raise before any
        # generator is created (mirrors AJ-19's pattern).
        self._ensure_gemini_model(model)
        system_instruction, contents = self._convert_messages(messages)
        config = self._build_config(
            system_instruction=system_instruction,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        kwargs: dict[str, Any] = {"model": model, "contents": contents}
        if config is not None:
            kwargs["config"] = config

        aio_models = self._aio_models

        async def _generator() -> AsyncIterator[Chunk]:
            sdk_stream: Any = None
            terminated = False
            try:
                sdk_stream = aio_models.generate_content_stream(**kwargs)
                # The SDK may return either a coroutine that resolves to an
                # async iterator, or the iterator directly. Await if needed.
                if hasattr(sdk_stream, "__await__"):
                    sdk_stream = await sdk_stream
                async for event in cast("AsyncIterator[Any]", sdk_stream):
                    for chunk in self._convert_stream_event(event):
                        if chunk.finish_reason is not None:
                            terminated = True
                        yield chunk
                        if terminated:
                            return
            except _RETRIABLE_SDK_EXCEPTIONS as exc:
                raise GeminiProviderError(f"Gemini SDK error during stream(): {exc}") from exc
            finally:
                # Best-effort: close the underlying iterator on early exit so
                # we do not leak HTTP sockets if the caller breaks out of
                # the iterator or calls aclose().
                aclose: Any = getattr(sdk_stream, "aclose", None)
                if callable(aclose):
                    try:
                        result: Any = aclose()
                        if hasattr(result, "__await__"):
                            await result
                    except Exception:
                        # Closing is best-effort; never let it mask a real
                        # exception bubbling up from the stream body.
                        _LOGGER.debug("Gemini stream aclose() failed", exc_info=True)

        return _generator()

    @override
    async def embed(
        self,
        *,
        model: str,
        text: str | list[str],
    ) -> list[list[float]]:
        # Defence-in-depth: the registry maps embedding model prefixes to
        # this provider; reject anything that isn't an embedding model so
        # callers cannot accidentally pass a generation model.
        if not model.startswith(_GEMINI_EMBEDDING_PREFIXES):
            raise GeminiProviderError(
                f"GeminiProvider.embed() requires an embedding model "
                f"({', '.join(_GEMINI_EMBEDDING_PREFIXES)}), got {model!r}."
            )
        # Normalise to a list so the SDK call shape is uniform regardless
        # of whether the caller passed a single string or a batch.
        inputs = [text] if isinstance(text, str) else list(text)
        if not inputs:
            return []
        try:
            raw: Any = await self._aio_models.embed_content(model=model, contents=inputs)
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            raise GeminiProviderError(f"Gemini SDK error during embed(): {exc}") from exc

        # ``raw.embeddings`` is a list of ``ContentEmbedding`` ordered by
        # input index; each carries a ``.values`` float vector.
        embeddings = cast("list[Any]", getattr(raw, "embeddings", None) or [])
        return [list(getattr(item, "values", None) or []) for item in embeddings]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        # The SDK ships an async ``count_tokens`` endpoint. We only call it
        # when we are NOT already inside an event loop — otherwise we
        # cannot synchronously wait and falling back to the char estimate
        # is the right thing to do. Matches AJ-19's pattern verbatim.
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if not in_loop:
            try:
                result: Any = asyncio.run(self._aio_models.count_tokens(model=model, contents=text))
                total = getattr(result, "total_tokens", None)
                if isinstance(total, int):
                    return total
            except Exception as exc:
                _LOGGER.warning(
                    "Gemini count_tokens failed (%s); falling back to estimate.",
                    exc,
                )
                return _estimate_tokens(text)
            # SDK returned something without a usable total — warn and fall
            # back to the char estimate so the caller never gets ``0``.
            _LOGGER.warning(
                "Gemini count_tokens returned no total_tokens; falling back to estimate."
            )
            return _estimate_tokens(text)

        _LOGGER.warning(
            "Gemini count_tokens called inside a running event loop; falling back to estimate."
        )
        return _estimate_tokens(text)

    @override
    def supports_prompt_caching(self) -> bool:
        # Gemini's prompt caching requires an explicit ``cachedContent``
        # lifecycle that does not fit the stateless ``cache: bool`` flag
        # shared across providers. Honestly advertise ``False``; the full
        # lifecycle lives in AJ-58.
        return False

    @override
    def supports_tool_calling(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_gemini_model(model: str) -> None:
        if not model.startswith(_GEMINI_MODEL_PREFIXES):
            raise GeminiProviderError(
                f"GeminiProvider only supports Gemini-family models "
                f"({', '.join(_GEMINI_MODEL_PREFIXES)}), got {model!r}. "
                f"Check the registry routing or pass a supported model."
            )

    @staticmethod
    def _convert_messages(
        messages: list[Message],
    ) -> tuple[str | None, list[genai_types.Content]]:
        """Translate framework messages to Gemini's wire shape.

        Gemini's API takes the system prompt as a top-level
        ``system_instruction`` config field, with the rest of the
        conversation in ``contents=[]``. Framework ``role="assistant"``
        maps to Gemini ``role="model"``; ``role="tool"`` maps to a
        ``user``-role content carrying a ``function_response`` part.

        Empty conversations and system-only conversations raise before
        the SDK is called — Gemini rejects empty ``contents=[]`` with a
        generic 400 that's hard to map back to a framework concept.
        """
        if not messages:
            raise GeminiProviderError(
                "GeminiProvider requires at least one user message; got an empty list."
            )

        system_parts: list[str] = []
        contents: list[genai_types.Content] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=msg.content)],
                    )
                )
            elif msg.role == "assistant":
                parts: list[genai_types.Part] = []
                if msg.content:
                    parts.append(genai_types.Part(text=msg.content))
                for call in msg.tool_calls:
                    parts.append(
                        genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                id=call.id,
                                name=call.name,
                                args=dict(call.arguments),
                            )
                        )
                    )
                if not parts:
                    # Gemini rejects a Content with an empty parts list; if
                    # neither text nor tool calls are present, surface a
                    # blank text part so the role survives the round-trip.
                    parts.append(genai_types.Part(text=""))
                contents.append(genai_types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                if not msg.tool_call_id:
                    raise GeminiProviderError(
                        "Gemini tool messages require tool_call_id "
                        f"(framework Message: name={msg.name!r}, content={msg.content!r})."
                    )
                # Gemini's function_response.response must be a dict; the
                # framework's wire type carries the result as a string. Wrap
                # it under a stable key so the model can read it back.
                response_payload: dict[str, Any] = {"content": msg.content}
                if msg.is_error:
                    response_payload["is_error"] = True
                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[
                            genai_types.Part(
                                function_response=genai_types.FunctionResponse(
                                    id=msg.tool_call_id,
                                    name=msg.name or "",
                                    response=response_payload,
                                )
                            )
                        ],
                    )
                )

        if not contents:
            raise GeminiProviderError(
                "GeminiProvider requires at least one user/assistant/tool turn; "
                "got only system messages."
            )

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    @staticmethod
    def _convert_tools(tools: list[Tool]) -> list[genai_types.Tool]:
        """Translate framework tools to Gemini's ``function_declarations`` shape."""
        return [
            genai_types.Tool(
                function_declarations=[
                    genai_types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters_json_schema=tool.parameters,
                    )
                ]
            )
            for tool in tools
        ]

    @classmethod
    def _build_config(
        cls,
        *,
        system_instruction: str | None,
        tools: list[Tool] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> genai_types.GenerateContentConfig | None:
        """Assemble a ``GenerateContentConfig`` from the optional knobs.

        Returns ``None`` when none of the knobs are set so the SDK call
        stays terse for the simple path.
        """
        if system_instruction is None and not tools and temperature is None and max_tokens is None:
            return None
        kwargs: dict[str, Any] = {}
        if system_instruction is not None:
            kwargs["system_instruction"] = system_instruction
        if tools:
            kwargs["tools"] = cls._convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        return genai_types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _convert_response(raw: Any) -> Response:
        """Decode a Gemini ``GenerateContentResponse`` into the framework ``Response``."""
        candidates = cast("list[Any]", getattr(raw, "candidates", None) or [])
        first: Any = candidates[0] if candidates else None
        content: Any = getattr(first, "content", None)
        parts = cast("list[Any]", getattr(content, "parts", None) or [])

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call is not None:
                args_obj: Any = getattr(function_call, "args", None) or {}
                tool_calls.append(
                    ToolCall(
                        id=str(getattr(function_call, "id", "") or ""),
                        name=str(getattr(function_call, "name", "") or ""),
                        arguments=dict(args_obj),
                    )
                )
                continue
            text_value = getattr(part, "text", None)
            if isinstance(text_value, str):
                text_parts.append(text_value)

        usage = getattr(raw, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "response_token_count", 0) or 0)

        finish_reason_raw = getattr(first, "finish_reason", None)
        mapped, raw_reason = _map_finish_reason(finish_reason_raw)
        if raw_reason is not None:
            _LOGGER.warning("Gemini finished with reason=%r; surfacing as 'error'.", raw_reason)
        # If the model produced tool calls, surface ``tool_calls`` so the
        # framework layer can dispatch them — matches Anthropic/OpenAI.
        if tool_calls and mapped == "stop":
            mapped = "tool_calls"

        return Response(
            text="".join(text_parts),
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            finish_reason=mapped,
        )

    @staticmethod
    def _convert_stream_event(event: Any) -> list[Chunk]:
        """Map a single Gemini stream event to wire-level chunks.

        Gemini emits one ``GenerateContentResponse`` per server push;
        each push's first candidate carries the incremental ``parts``
        (text or function call) plus an optional ``finish_reason`` once
        the model is done. A single SDK event can carry both a text
        delta and a function call, so this helper may return more than
        one wire-level :class:`Chunk`.
        """
        emitted: list[Chunk] = []

        candidates = cast("list[Any]", getattr(event, "candidates", None) or [])
        first: Any = candidates[0] if candidates else None
        content: Any = getattr(first, "content", None)
        parts = cast("list[Any]", getattr(content, "parts", None) or [])

        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call is not None:
                args_obj: Any = getattr(function_call, "args", None) or {}
                # Gemini emits the function call in a single chunk (not
                # progressively); surface the full payload at once so the
                # consumer does not have to buffer partial JSON.
                emitted.append(
                    Chunk(
                        delta="",
                        tool_call_delta=ToolCallDelta(
                            id=str(getattr(function_call, "id", "") or ""),
                            name=str(getattr(function_call, "name", "") or ""),
                            arguments_delta=json.dumps(dict(args_obj)),
                        ),
                    )
                )
                continue
            text_value = getattr(part, "text", None)
            if isinstance(text_value, str) and text_value:
                emitted.append(Chunk(delta=text_value))

        finish_reason_raw = getattr(first, "finish_reason", None)
        if finish_reason_raw is not None:
            mapped, raw_reason = _map_finish_reason(finish_reason_raw)
            if raw_reason is not None:
                _LOGGER.warning(
                    "Gemini stream finished with reason=%r; surfacing as 'error'.",
                    raw_reason,
                )
            emitted.append(Chunk(delta="", finish_reason=mapped))

        return emitted
