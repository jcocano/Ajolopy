"""``GeminiProvider`` — concrete ``LLMProvider`` over the Google Gen AI SDK.

Bridges the framework's provider-agnostic wire types to Google's native
Gemini API via the official ``google-genai`` Python SDK. The implementation
keeps the surface narrow on top: multimodal inputs, grounding / Google
Search retrieval and Vertex AI specific knobs stay deferred to later
board items.

AJ-58 adds an opt-in Context Caching lifecycle on top of AJ-21's
baseline. The provider is constructed with six caching kwargs (all
defaulted to a no-op posture so AJ-21's behaviour is preserved); flipping
``cache_strategy="auto"`` activates create / reuse / recreate-on-expired
/ delete-on-close around the existing ``complete()`` / ``stream()``
paths. The lifecycle helpers (``CacheRegistry``, ``prefix_hash_cache_key``,
the cache-related literal types) live in :mod:`ajolopy.providers.gemini.cache`
so this module stays focused on SDK wiring.

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
    ChunkUsage,
    FinishReason,
    Message,
    Response,
    Tool,
    ToolCall,
    ToolCallDelta,
)

from .cache import (
    CacheCleanup,
    CacheKeyStrategy,
    CacheOnExpired,
    CacheRegistry,
    CacheStrategy,
    prefix_hash_cache_key,
)
from .errors import (
    GeminiCacheCreateError,
    GeminiCacheError,
    GeminiCacheExpiredError,
    GeminiCacheMinTokensError,
    GeminiConfigError,
    GeminiProviderError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from types import TracebackType

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


def _is_not_found(exc: BaseException) -> bool:
    """Whether an SDK exception represents a 404 referencing a missing resource.

    Used by the cache-expiry detour: when a ``generate_content`` call
    references a ``cached_content`` whose TTL has elapsed, the SDK
    surfaces a 404 ``APIError``. We probe the integer ``code`` attribute
    rather than relying on the SDK exception class hierarchy because
    ``APIError`` is the shared base for both client and server families
    and the AJ-21 mocks construct it directly.
    """
    code = getattr(exc, "code", None)
    return code == 404


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


def _first_user_content(messages: list[Message]) -> str:
    """Return the first ``user`` message's content, or an empty string.

    Used to mirror ``prefix_hash_cache_key`` for the minimum-tokens gate:
    the framework counts tokens over the same prefix the default key
    strategy hashes, so the gate stays consistent with the cache identity.
    """
    for msg in messages:
        if msg.role == "user":
            return msg.content
    return ""


def _describe_callable(fn: Callable[..., Any]) -> str:
    """Best-effort string name for a callable, for error messages."""
    return getattr(fn, "__qualname__", None) or getattr(fn, "__name__", None) or repr(fn)


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

    GEN_AI_SYSTEM = "gcp.gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: genai.Client | None = None,
        # AJ-58 — Context Caching lifecycle. Defaults to ``"off"`` so the
        # provider behaves identically to AJ-21's release; the opt-in
        # surface is a single kwarg flip plus optional per-knob overrides.
        cache_strategy: CacheStrategy = "off",
        cache_ttl_seconds: int = 3600,
        cache_min_tokens: int = 1024,
        cache_key_strategy: CacheKeyStrategy = "prefix_hash",
        cache_on_expired: CacheOnExpired = "recreate",
        cache_cleanup: CacheCleanup = "on_provider_close",
    ) -> None:
        # Validate the numeric knobs up front so misconfiguration surfaces
        # at construction time rather than on the first cache-eligible call.
        if cache_ttl_seconds <= 0:
            raise ValueError(
                f"cache_ttl_seconds must be a positive integer; got {cache_ttl_seconds!r}."
            )
        if cache_min_tokens <= 0:
            raise ValueError(
                f"cache_min_tokens must be a positive integer; got {cache_min_tokens!r}."
            )

        if client is not None:
            self._client = client
        elif api_key is not None:
            self._client = genai.Client(api_key=api_key)
        else:
            # Fall back to env var. ``genai.Client()`` reads it itself but
            # its error surfaces only on the first request; check up front
            # so the framework bootstrap fails before a single call is made.
            if not os.environ.get("GEMINI_API_KEY"):
                raise GeminiConfigError(
                    "GEMINI_API_KEY missing — pass api_key=, client=, or set the env var."
                )
            self._client = genai.Client()

        self._cache_strategy: CacheStrategy = cache_strategy
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_min_tokens = cache_min_tokens
        self._cache_key_strategy: CacheKeyStrategy = cache_key_strategy
        self._cache_on_expired: CacheOnExpired = cache_on_expired
        self._cache_cleanup: CacheCleanup = cache_cleanup
        self._cache_registry = CacheRegistry()

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

    @property
    def _aio_caches(self) -> Any:
        """Return ``client.aio.caches`` cast to ``Any``.

        Parallel to :pyattr:`_aio_models` — the cache-resource endpoints
        carry the same untyped ``ContentListUnion`` shape on
        ``CreateCachedContentConfig`` that pyright cannot narrow. The
        cast keeps the cache lifecycle code path readable; the tech-debt
        ticket on the wider typing situation lives in AJ-59.
        """
        return cast("Any", self._client.aio.caches)

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
        # When the caller did NOT opt into the AJ-58 caching lifecycle the
        # ``cache`` flag stays a documented no-op (matches AJ-21's release).
        # Flipping ``cache_strategy="auto"`` plus ``cache=True`` activates
        # the lifecycle: derive a key, create-or-reuse the server-side
        # cache resource, and reference it via ``cached_content``.
        self._ensure_gemini_model(model)
        system_instruction, contents = self._convert_messages(messages)

        cache_active = cache and self._cache_strategy == "auto"
        cache_key: str | None = None
        cache_name: str | None = None
        if cache_active:
            cache_key = self._derive_cache_key(messages, system_instruction)
            cache_name = await self._resolve_cache_name(
                cache_key=cache_key,
                model=model,
                messages=messages,
                system_instruction=system_instruction,
            )

        config = self._build_config(
            system_instruction=system_instruction,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            cached_content=cache_name,
        )
        kwargs: dict[str, Any] = {"model": model, "contents": contents}
        if config is not None:
            kwargs["config"] = config

        try:
            raw: Any = await self._aio_models.generate_content(**kwargs)
        except _RETRIABLE_SDK_EXCEPTIONS as exc:
            # Cache-expiry detour. A 404 referencing the cached content
            # means the TTL elapsed between create and the second call.
            # ``recreate``: drop the stale name, build a fresh cache,
            # retry once. ``error``: surface a typed cache-expiry error.
            if (
                cache_active
                and cache_key is not None
                and cache_name is not None
                and _is_not_found(exc)
            ):
                if self._cache_on_expired == "error":
                    raise GeminiCacheExpiredError(
                        f"Gemini cache {cache_name!r} expired; "
                        "set cache_on_expired='recreate' or retry as a fresh call."
                    ) from exc
                _LOGGER.info("Gemini cache %r expired; recreating transparently.", cache_name)
                self._cache_registry.drop_name(cache_key, cache_name)
                new_name = await self._create_cache(
                    model=model,
                    messages=messages,
                    system_instruction=system_instruction,
                )
                self._cache_registry.register(cache_key, new_name)
                retry_config = self._build_config(
                    system_instruction=system_instruction,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    cached_content=new_name,
                )
                retry_kwargs: dict[str, Any] = {"model": model, "contents": contents}
                if retry_config is not None:
                    retry_kwargs["config"] = retry_config
                try:
                    raw = await self._aio_models.generate_content(**retry_kwargs)
                except _RETRIABLE_SDK_EXCEPTIONS as retry_exc:
                    raise GeminiProviderError(
                        f"Gemini SDK error during complete() after cache recreate: {retry_exc}"
                    ) from retry_exc
                return self._convert_response(raw)
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
        # Validate eagerly so configuration errors raise before any
        # generator is created (mirrors AJ-19's pattern).
        self._ensure_gemini_model(model)
        system_instruction, contents = self._convert_messages(messages)
        cache_active = cache and self._cache_strategy == "auto"
        # When caching is active we derive the key eagerly so the spec's
        # error-on-derive cases (custom callable raising or returning a
        # falsy value) surface before the iterator is awaited. The
        # streaming path never replays on 404 — see the spec's "Expiry
        # handling" section for why ``cache_on_expired`` does not apply.
        cache_key = self._derive_cache_key(messages, system_instruction) if cache_active else None

        async def _generator() -> AsyncIterator[Chunk]:
            cache_name: str | None = None
            if cache_active and cache_key is not None:
                cache_name = await self._resolve_cache_name(
                    cache_key=cache_key,
                    model=model,
                    messages=messages,
                    system_instruction=system_instruction,
                )
            config = self._build_config(
                system_instruction=system_instruction,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                cached_content=cache_name,
            )
            kwargs: dict[str, Any] = {"model": model, "contents": contents}
            if config is not None:
                kwargs["config"] = config

            sdk_stream: Any = None
            terminated = False
            try:
                sdk_stream = self._aio_models.generate_content_stream(**kwargs)
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
                # Streaming + cache expiry: surface a typed cache-expiry
                # error regardless of ``cache_on_expired``. Recreate is
                # not possible without buffering the full output — see
                # the spec's "Expiry handling" section for the rationale.
                if (
                    cache_active
                    and cache_key is not None
                    and cache_name is not None
                    and _is_not_found(exc)
                ):
                    self._cache_registry.drop_name(cache_key, cache_name)
                    raise GeminiCacheExpiredError(
                        f"Gemini cache {cache_name!r} expired mid-stream; "
                        "retry the request as a fresh call (streaming cannot replay)."
                    ) from exc
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
        # AJ-58: honestly reflect the per-instance state of the cache
        # lifecycle. ``cache_strategy="off"`` (default, AJ-21-compatible)
        # advertises ``False`` so the framework / @Agent does not pass
        # ``cache=True`` on the wire. ``"auto"`` flips it to ``True``.
        return self._cache_strategy == "auto"

    @override
    def supports_tool_calling(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # AJ-58 — cache lifecycle (opt-in via ``cache_strategy="auto"``)
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Release the provider's transient state.

        When ``cache_cleanup="on_provider_close"`` (the default) every
        tracked cache name is best-effort deleted on the server. Other
        cleanup is best-effort too — a single ``caches.delete`` failure
        does not abort the shutdown. ``manual`` mode leaves cache names
        in the registry for the caller to clean up explicitly.

        Idempotent: calling twice is a no-op once the registry has been
        cleared. Concurrent calls observe whatever is in the registry
        at the moment of the snapshot; caches registered afterwards by
        an in-flight ``complete()`` survive until garbage collection.

        Provider-specific in v0.1: the ``LLMProvider`` ABC does not
        declare ``aclose()`` because only Gemini owns server-side state
        the framework opts to manage. Promote to the ABC in a future
        item if a generalised shutdown protocol is needed.
        """
        if self._cache_cleanup != "on_provider_close":
            return
        snapshot = self._cache_registry.snapshot()
        if not snapshot:
            return
        # Take a snapshot then clear the registry up-front so re-entrant
        # ``aclose()`` calls (idempotency) immediately become no-ops.
        self._cache_registry.clear()
        aio_caches = self._aio_caches
        for _key, name in snapshot:
            try:
                await aio_caches.delete(name=name)
            except Exception as exc:
                # Server-side caches expire naturally; a 404 / 5xx on
                # delete is not actionable during shutdown. Log and move
                # on so the remaining names still get a delete attempt.
                _LOGGER.warning(
                    "Gemini cache delete %r failed during shutdown (%s); ignoring.",
                    name,
                    exc,
                )

    async def __aenter__(self) -> GeminiProvider:
        """Make the provider usable as an async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Suppress nothing: we always return ``None`` (and the implicit
        # falsy return) so exceptions propagate. The kwargs are unused
        # in the cleanup logic itself but match the protocol's contract.
        _ = (exc_type, exc_value, traceback)
        await self.aclose()

    def _derive_cache_key(
        self,
        messages: list[Message],
        system_instruction: str | None,
    ) -> str:
        """Derive the cache key for a request using the configured strategy.

        ``"prefix_hash"`` (default) uses the built-in SHA-256 prefix hash.
        A ``Callable`` is invoked with ``(messages, system_instruction)``
        and its return value is used verbatim. Wrap callable failures as
        ``GeminiCacheError`` and refuse empty / falsy return values —
        empty cache keys collide silently in the registry.
        """
        strategy = self._cache_key_strategy
        if strategy == "prefix_hash":
            return prefix_hash_cache_key(messages, system_instruction)
        if callable(strategy):
            try:
                derived = strategy(messages, system_instruction)
            except Exception as exc:
                raise GeminiCacheError(
                    f"Custom cache_key_strategy {_describe_callable(strategy)} "
                    f"raised {type(exc).__name__}: {exc}"
                ) from exc
            if not derived:
                raise GeminiCacheError(
                    f"Custom cache_key_strategy {_describe_callable(strategy)} "
                    f"returned falsy value {derived!r}; cache keys must be non-empty strings."
                )
            return derived
        # Defence-in-depth — should be unreachable thanks to the literal
        # type annotation. Surface a typed error rather than crashing.
        raise GeminiCacheError(
            f"Unrecognised cache_key_strategy {strategy!r}; expected 'prefix_hash' or a callable."
        )

    async def _resolve_cache_name(
        self,
        *,
        cache_key: str,
        model: str,
        messages: list[Message],
        system_instruction: str | None,
    ) -> str:
        """Return the cache name to reference on the upcoming SDK call.

        Reuses an existing entry from the registry if present, otherwise
        gates on ``cache_min_tokens`` and creates a fresh cache. The
        token-minimum check fires *before* any ``caches.create`` SDK call
        so callers see a typed framework error instead of paying for a
        wasted server-side resource.
        """
        existing = self._cache_registry.latest(cache_key)
        if existing is not None:
            return existing
        # No existing cache — gate on minimum tokens first.
        text_for_count = (system_instruction or "") + "\n\n" + _first_user_content(messages)
        token_count = self.count_tokens(model=model, text=text_for_count)
        if token_count < self._cache_min_tokens:
            raise GeminiCacheMinTokensError(
                f"Gemini cache_min_tokens={self._cache_min_tokens} not met "
                f"(got ~{token_count} tokens); shorten the prompt, override "
                f"cache_min_tokens at construction, or call with cache=False."
            )
        name = await self._create_cache(
            model=model,
            messages=messages,
            system_instruction=system_instruction,
        )
        self._cache_registry.register(cache_key, name)
        return name

    async def _create_cache(
        self,
        *,
        model: str,
        messages: list[Message],
        system_instruction: str | None,
    ) -> str:
        """Issue a ``caches.create`` SDK call and return the server-assigned name.

        Wraps ``CreateCachedContentConfig`` from the SDK with the contents
        we want cached (the framework-converted messages, minus any
        ``tool``-role parts which are conversation-turn payloads not
        suited for caching) and the configured TTL as a duration string.
        """
        _system, contents = self._convert_messages(messages)
        ttl = f"{self._cache_ttl_seconds}s"
        config = genai_types.CreateCachedContentConfig(
            ttl=ttl,
            system_instruction=system_instruction,
            contents=contents,
        )
        try:
            created: Any = await self._aio_caches.create(model=model, config=config)
        except Exception as exc:
            raise GeminiCacheCreateError(
                f"Gemini caches.create failed for model={model!r}: {exc}"
            ) from exc
        name = getattr(created, "name", None)
        if not isinstance(name, str) or not name:
            raise GeminiCacheCreateError(
                f"Gemini caches.create returned no usable cache name (got {name!r})."
            )
        return name

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
        cached_content: str | None = None,
    ) -> genai_types.GenerateContentConfig | None:
        """Assemble a ``GenerateContentConfig`` from the optional knobs.

        Returns ``None`` when none of the knobs are set so the SDK call
        stays terse for the simple path. ``cached_content`` carries the
        server-assigned cache name produced by AJ-58's lifecycle.
        """
        if (
            system_instruction is None
            and not tools
            and temperature is None
            and max_tokens is None
            and cached_content is None
        ):
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
        if cached_content is not None:
            kwargs["cached_content"] = cached_content
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
        # Gemini reports cache hits under ``cached_content_token_count``.
        # Cache *creation* is billed as part of input on Gemini, so the
        # creation tier stays 0 here — mirrors the OpenAI policy.
        cache_read = int(getattr(usage, "cached_content_token_count", 0) or 0)

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
            cache_read_input_tokens=cache_read,
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
            # Gemini reports cumulative usage on every stream event under
            # ``usage_metadata``; the terminal event carries the final totals.
            usage_metadata = getattr(event, "usage_metadata", None)
            usage: ChunkUsage | None = None
            if usage_metadata is not None:
                input_tokens = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
                output_tokens = int(getattr(usage_metadata, "response_token_count", 0) or 0)
                cache_read = int(getattr(usage_metadata, "cached_content_token_count", 0) or 0)
                if input_tokens > 0 or output_tokens > 0 or cache_read > 0:
                    usage = ChunkUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_input_tokens=cache_read,
                    )
            emitted.append(Chunk(delta="", finish_reason=mapped, usage=usage))

        return emitted
