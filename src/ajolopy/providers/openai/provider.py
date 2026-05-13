"""``OpenAIProvider`` — concrete ``LLMProvider`` over the OpenAI SDK.

Bridges the framework's provider-agnostic wire types to OpenAI's native
Chat Completions API. The implementation deliberately keeps the surface
narrow: features that need framework-wide buy-in (reasoning-effort knobs
for ``o1``/``o3``, structured outputs with ``response_format``, vision,
audio) are deferred until they land as separate board items.

Wire-level conversion helpers (messages, tools, response decoding,
streaming events) live in :mod:`ajolopy.providers._openai_helpers` so
they can be shared with :class:`UniversalOpenAIProvider`.
"""

import logging
import os
from typing import TYPE_CHECKING, Any, cast, override

import openai

from ajolopy.providers._openai_helpers import (
    RETRIABLE_SDK_EXCEPTIONS,
    convert_messages,
    convert_response,
    convert_stream_event,
    convert_tools,
    estimate_tokens,
)
from ajolopy.providers.base import LLMProvider

from .errors import OpenAIConfigError, OpenAIProviderError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ajolopy.providers.types import (
        Chunk,
        Message,
        Response,
        Tool,
    )

_LOGGER = logging.getLogger(__name__)


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
            "messages": convert_messages(messages),
        }
        if tools:
            kwargs["tools"] = convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            raw = cast("Any", await self._client.chat.completions.create(**kwargs))
        except RETRIABLE_SDK_EXCEPTIONS as exc:
            raise OpenAIProviderError(f"OpenAI SDK error during complete(): {exc}") from exc

        return convert_response(raw, _LOGGER)

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
            "messages": convert_messages(messages),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        async def _generator() -> AsyncIterator[Chunk]:
            sdk_stream: Any = None
            try:
                sdk_stream = cast("Any", await self._client.chat.completions.create(**kwargs))
                async for event in cast("AsyncIterator[Any]", sdk_stream):
                    for chunk in convert_stream_event(event, _LOGGER):
                        yield chunk
            except RETRIABLE_SDK_EXCEPTIONS as exc:
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
        except RETRIABLE_SDK_EXCEPTIONS as exc:
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
            return estimate_tokens(text)

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
