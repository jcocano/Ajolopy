"""``UniversalOpenAIProvider`` — one ``LLMProvider`` over many OpenAI-compatible APIs.

Ollama, Groq, Together, Mistral, DeepSeek, and OpenRouter all speak the
OpenAI wire format, so they share one provider class. Each prefix has
its own default ``base_url`` and API-key env var; the provider keeps a
small table of ``_PrefixConfig`` entries and builds one ``AsyncOpenAI``
client lazily per prefix on first use, caching it for subsequent
requests. The constructor itself does no I/O and reads no env vars —
imports stay free for users that only need a subset of the prefixes.

The wire-level conversion helpers (messages → OpenAI chat shape, tools
→ function-calling schema, response decoding, streaming-event
decoding) live in :mod:`ajolopy.providers._openai_helpers` and are
shared with :class:`OpenAIProvider` (AJ-20).
"""

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn, cast, override

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

from .errors import (
    UniversalEmbeddingsNotSupportedError,
    UniversalProviderConfigError,
    UniversalProviderError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from ajolopy.providers.types import (
        Chunk,
        Message,
        Response,
        Tool,
    )

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PrefixDefaults:
    """Per-prefix defaults baked into the provider.

    ``api_key_env`` is ``None`` for prefixes that require no API key
    (currently only ``ollama``, which runs locally and accepts the
    placeholder ``"ollama"`` literal — the SDK requires a non-empty
    string but Ollama itself ignores it).

    ``supports_embed`` mirrors the capability table in the spec. The
    four prefixes that do not ship an embeddings endpoint raise
    :class:`UniversalEmbeddingsNotSupportedError` on :meth:`embed`.
    """

    default_base_url: str
    api_key_env: str | None
    supports_embed: bool


# Spec table: every prefix supported in v0.1. Adding a new prefix is a
# matter of appending an entry plus a routing rule in
# ``ajolopy.providers.registry`` — no other code changes needed.
_PREFIX_DEFAULTS: dict[str, _PrefixDefaults] = {
    "ollama": _PrefixDefaults(
        default_base_url="http://localhost:11434/v1",
        api_key_env=None,
        supports_embed=True,
    ),
    "groq": _PrefixDefaults(
        default_base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        supports_embed=False,
    ),
    "together": _PrefixDefaults(
        default_base_url="https://api.together.xyz/v1",
        api_key_env="TOGETHER_API_KEY",
        supports_embed=True,
    ),
    "mistral": _PrefixDefaults(
        default_base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        supports_embed=True,
    ),
    "deepseek": _PrefixDefaults(
        default_base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        supports_embed=False,
    ),
    "openrouter": _PrefixDefaults(
        default_base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        supports_embed=False,
    ),
}


def _split_prefix(model: str) -> tuple[str, str]:
    """Split a ``"<prefix>:<model>"`` string into its two halves.

    Raises :class:`UniversalProviderError` for a bare model string with
    no universal prefix, an empty prefix, or an empty model part.
    """
    if ":" not in model:
        known = sorted(_PREFIX_DEFAULTS.keys())
        raise UniversalProviderError(
            f"UniversalOpenAIProvider expects a prefixed model "
            f"(e.g. 'groq:llama-3.3-70b-versatile'); got {model!r}. "
            f"Supported prefixes: {known!r}."
        )
    prefix, _, rest = model.partition(":")
    if not prefix or not rest:
        raise UniversalProviderError(
            f"Malformed universal model string {model!r} — expected "
            f"'<prefix>:<model>' with non-empty halves."
        )
    return prefix, rest


class UniversalOpenAIProvider(LLMProvider):
    """``LLMProvider`` that fans every OpenAI-compatible API through one class.

    Construction is side-effect-free: no env vars are read, no clients
    are built. Each prefix's client is constructed lazily on the first
    request that targets it and cached for the lifetime of the
    provider.

    Escape hatches:

    - ``api_keys={"groq": "gsk_..."}`` — per-prefix API key override;
      the env var is never consulted for the overridden prefix.
    - ``base_urls={"ollama": "http://my-ollama.lan:11434/v1"}`` —
      per-prefix endpoint override (e.g. a remote Ollama instance).
      Wins over the env-var lookup below.
    - ``${PREFIX}_BASE_URL`` env var — per-prefix endpoint override
      read lazily on the first request for the prefix (e.g.
      ``OLLAMA_BASE_URL``, ``GROQ_BASE_URL``, ``TOGETHER_BASE_URL``,
      ``MISTRAL_BASE_URL``, ``DEEPSEEK_BASE_URL``,
      ``OPENROUTER_BASE_URL``). Empty string falls through to the
      baked-in default. Precedence is ``base_urls=`` kwarg > env var >
      baked-in default.
    - ``clients={"groq": openai.AsyncOpenAI(...)}`` — pre-built SDK
      client. Wins over both other kwargs and over the per-prefix
      defaults; used by callers that need custom transport.

    For prefixes outside the spec's v0.1 table (`vllm:*`, anything
    else), subclass and override :meth:`_resolve_client` after
    registering the new route with :func:`register_route`.
    """

    GEN_AI_SYSTEM = "openai_compatible"

    @classmethod
    @override
    def gen_ai_system_for(cls, model: str) -> str:
        """Return ``openai_compatible.<prefix>`` so observability backends can
        differentiate spans by upstream provider (Groq vs Ollama vs Together).

        The model string is required to follow the ``"<prefix>:<model>"``
        contract documented on this class. When the string is malformed we
        return the bare ``openai_compatible`` value — span emission must never
        crash because a span attribute could not be computed; the actual
        request will fail loudly downstream.
        """
        try:
            prefix, _ = _split_prefix(model)
        except UniversalProviderError:
            return cls.GEN_AI_SYSTEM
        return f"{cls.GEN_AI_SYSTEM}.{prefix}"

    def __init__(
        self,
        *,
        api_keys: Mapping[str, str] | None = None,
        base_urls: Mapping[str, str] | None = None,
        clients: Mapping[str, openai.AsyncOpenAI] | None = None,
    ) -> None:
        # Copy the inputs into private dicts so callers cannot mutate
        # them after construction. Empty mappings are normalised to
        # ``{}`` so the lookup paths stay uniform.
        self._api_key_overrides: dict[str, str] = dict(api_keys or {})
        self._base_url_overrides: dict[str, str] = dict(base_urls or {})
        # Pre-built clients populate the cache directly; they bypass
        # the lazy-build path entirely.
        self._clients: dict[str, openai.AsyncOpenAI] = dict(clients or {})
        # Set of prefixes for which ``count_tokens`` has already emitted
        # its one-time warning. Keeps log noise down on hot paths.
        self._warned_count_tokens_prefixes: set[str] = set()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

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
        # ``cache=True`` is a no-op for universal providers: none of
        # them expose an opt-in caching flag. ``supports_prompt_caching``
        # returns False so callers know the feature is unavailable.
        _ = cache
        prefix, sdk_model = _split_prefix(model)
        client = self._resolve_client(prefix)
        kwargs: dict[str, Any] = {
            "model": sdk_model,
            "messages": convert_messages(messages),
        }
        if tools:
            kwargs["tools"] = convert_tools(tools)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            raw = cast("Any", await client.chat.completions.create(**kwargs))
        except RETRIABLE_SDK_EXCEPTIONS as exc:
            raise UniversalProviderError(
                f"Universal-OpenAI SDK error during complete() for prefix {prefix!r}: {exc}"
            ) from exc

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
        prefix, sdk_model = _split_prefix(model)
        client = self._resolve_client(prefix)
        kwargs: dict[str, Any] = {
            "model": sdk_model,
            "messages": convert_messages(messages),
            "stream": True,
            # OpenAI-compatible extension: when the upstream understands the
            # flag, it will emit a terminal usage-only chunk that the helper
            # converts to ``Chunk(usage=...)`` for the runtime to read. When
            # the upstream silently ignores it (Ollama, llama.cpp, etc.) the
            # stream still works — ``Chunk.usage`` simply stays ``None``.
            "stream_options": {"include_usage": True},
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
                sdk_stream = cast("Any", await client.chat.completions.create(**kwargs))
                async for event in cast("AsyncIterator[Any]", sdk_stream):
                    for chunk in convert_stream_event(event, _LOGGER):
                        yield chunk
            except RETRIABLE_SDK_EXCEPTIONS as exc:
                raise UniversalProviderError(
                    f"Universal-OpenAI SDK error during stream() for prefix {prefix!r}: {exc}"
                ) from exc
            finally:
                # Best-effort: cancel the underlying SSE connection on
                # early exit so we do not leak HTTP sockets if the caller
                # breaks out of the iterator or calls aclose().
                close: Any = getattr(sdk_stream, "close", None)
                if callable(close):
                    try:
                        result: Any = close()
                        if hasattr(result, "__await__"):
                            await result
                    except Exception:
                        # Closing is best-effort; never let it mask a
                        # real exception bubbling up from the stream body.
                        _LOGGER.debug(
                            "Universal-OpenAI stream close() failed",
                            exc_info=True,
                        )

        return _generator()

    @override
    async def embed(
        self,
        *,
        model: str,
        text: str | list[str],
    ) -> list[list[float]]:
        prefix, sdk_model = _split_prefix(model)
        defaults = _PREFIX_DEFAULTS.get(prefix)
        if defaults is None:
            # ``_resolve_client`` would raise on unknown prefixes too,
            # but covering the capability check here surfaces the
            # cleaner error message for embeddings callers.
            self._raise_unknown_prefix(prefix)
        elif not defaults.supports_embed:
            raise UniversalEmbeddingsNotSupportedError(
                f"Prefix {prefix!r} does not expose an embeddings endpoint. "
                f"Route embeddings to OpenAI's 'text-embedding-3-small' / "
                f"'text-embedding-3-large' instead — that is the framework's "
                f"documented fallback for providers without native embeddings."
            )
        client = self._resolve_client(prefix)

        # Normalise to a list so the SDK call shape is uniform regardless
        # of whether the caller passed a single string or a batch.
        inputs = [text] if isinstance(text, str) else list(text)
        if not inputs:
            return []
        try:
            raw = cast(
                "Any",
                await client.embeddings.create(model=sdk_model, input=inputs),
            )
        except RETRIABLE_SDK_EXCEPTIONS as exc:
            raise UniversalProviderError(
                f"Universal-OpenAI SDK error during embed() for prefix {prefix!r}: {exc}"
            ) from exc

        # ``raw.data`` is a list of ``Embedding`` objects ordered by
        # input index; each has a ``.embedding`` field with the vector.
        return [list(item.embedding) for item in raw.data]

    @override
    def count_tokens(self, *, model: str, text: str) -> int:
        prefix, _ = _split_prefix(model)
        if prefix not in _PREFIX_DEFAULTS:
            self._raise_unknown_prefix(prefix)
        if prefix not in self._warned_count_tokens_prefixes:
            # First time the caller asks for a token count on this
            # prefix — log a one-time warning explaining that the
            # tokenizer is OpenAI's, not the underlying model's.
            self._warned_count_tokens_prefixes.add(prefix)
            _LOGGER.warning(
                "UniversalOpenAIProvider count_tokens for prefix %r uses the gpt-4o "
                "tokenizer as a default; the actual model tokenizer may differ. "
                "Treat the value as an estimate.",
                prefix,
            )
        try:
            import tiktoken

            # Llama / Mixtral / DeepSeek tokenizers differ from OpenAI's
            # o200k_base, but tiktoken is the only offline option that
            # ships pre-built wheels; gpt-4o's encoding is the closest
            # generic default available. Falls back to a char-based
            # estimate when tiktoken cannot resolve the encoding.
            encoding = tiktoken.encoding_for_model("gpt-4o")
            return max(1, len(encoding.encode(text)))
        except Exception as exc:
            _LOGGER.warning(
                "Universal-OpenAI count_tokens fell back to char estimate for "
                "prefix=%r model=%r (%s).",
                prefix,
                model,
                exc,
            )
            return estimate_tokens(text)

    @override
    def supports_prompt_caching(self) -> bool:
        # None of the OpenAI-compatible providers expose an opt-in
        # caching flag; whether the underlying model caches is opaque,
        # so the framework reports False.
        return False

    @override
    def supports_tool_calling(self) -> bool:
        # Every modern OpenAI-compatible API supports function-calling
        # tools on the wire format; per-model capabilities are the
        # caller's concern.
        return True

    # ------------------------------------------------------------------
    # internal helpers (subclass-overridable)
    # ------------------------------------------------------------------

    def _resolve_client(self, prefix: str) -> openai.AsyncOpenAI:
        """Return the cached SDK client for ``prefix``, building it lazily.

        Resolution order per prefix:

        1. Pre-built client supplied via ``clients=`` kwarg (also covers
           the cache populated by previous calls).
        2. ``base_url``: ``base_urls=`` constructor override, then the
           ``${PREFIX}_BASE_URL`` env var (read lazily — empty string
           falls through), then the per-prefix baked-in default.
        3. ``api_key``: ``api_keys=`` constructor override, then the
           per-prefix ``api_key_env`` env var.

        Subclasses extending the provider to new prefixes should
        override this method and call ``super()._resolve_client(prefix)``
        for the known cases.
        """
        cached = self._clients.get(prefix)
        if cached is not None:
            return cached
        defaults = _PREFIX_DEFAULTS.get(prefix)
        if defaults is None:
            self._raise_unknown_prefix(prefix)

        base_url = self._resolve_base_url(prefix, defaults)
        api_key = self._resolve_api_key(prefix, defaults)
        client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._clients[prefix] = client
        return client

    def _resolve_base_url(self, prefix: str, defaults: _PrefixDefaults) -> str:
        """Resolve the base URL for ``prefix`` from overrides, env, or default.

        Precedence (high to low):

        1. ``base_urls={"<prefix>": "..."}`` constructor override —
           wins over everything else.
        2. ``${PREFIX.upper()}_BASE_URL`` env var (``OLLAMA_BASE_URL``,
           ``GROQ_BASE_URL``, ``TOGETHER_BASE_URL``,
           ``MISTRAL_BASE_URL``, ``DEEPSEEK_BASE_URL``,
           ``OPENROUTER_BASE_URL``). Empty string is treated as "not
           set" — same convention as ``_resolve_api_key`` — and falls
           through to the default.
        3. ``defaults.default_base_url`` — the per-prefix value baked
           into ``_PREFIX_DEFAULTS``.

        Values are forwarded to ``openai.AsyncOpenAI`` verbatim; the
        env var is treated as trusted operator configuration (no
        scheme / host validation), matching how ``api_key_env`` is
        consumed today.
        """
        override = self._base_url_overrides.get(prefix)
        if override is not None:
            return override
        env_value = os.environ.get(f"{prefix.upper()}_BASE_URL")
        if env_value:
            return env_value
        return defaults.default_base_url

    def _resolve_api_key(self, prefix: str, defaults: _PrefixDefaults) -> str:
        """Resolve the API key for ``prefix`` from overrides or env var.

        Ollama's special case: ``api_key_env`` is ``None`` and the SDK
        is given the literal ``"ollama"`` (the SDK rejects empty
        strings; Ollama itself ignores the value). An explicit
        ``api_keys["ollama"]`` override still wins.
        """
        override = self._api_key_overrides.get(prefix)
        if override is not None:
            return override
        if defaults.api_key_env is None:
            # Ollama runs locally and accepts any non-empty placeholder.
            return "ollama"
        value = os.environ.get(defaults.api_key_env)
        if not value:
            raise UniversalProviderConfigError(
                f"Universal-OpenAI provider for prefix {prefix!r} is missing its API key. "
                f"Set {defaults.api_key_env!r} in the environment, or pass "
                f"api_keys={{{prefix!r}: ...}} or clients={{{prefix!r}: ...}} "
                f"to the constructor."
            )
        return value

    @staticmethod
    def _raise_unknown_prefix(prefix: str) -> NoReturn:
        # Azure has a route entry in ``_DEFAULT_ROUTES`` so the
        # resolver doesn't crash, but it needs ``AsyncAzureOpenAI``
        # plus deployment-vs-model routing — out of scope for v0.1.
        # Point at the deferred item explicitly so the message is
        # honest about the gap.
        if prefix == "azure":
            raise UniversalProviderError(
                "Azure OpenAI is not yet implemented — it needs the "
                "AsyncAzureOpenAI client class plus deployment-vs-model "
                "routing. Tracked separately; see Brief v4.0 §03."
            )
        known = sorted(_PREFIX_DEFAULTS.keys())
        raise UniversalProviderError(
            f"Unsupported universal prefix {prefix!r}. Supported prefixes: {known!r}."
        )
