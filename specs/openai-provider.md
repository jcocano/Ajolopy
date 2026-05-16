# AJ-20 — `OpenAIProvider`

> Tracked in [`board.json`](../board.json) as `AJ-20`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §03 (multi-provider — OpenAI
> entry) plus `01 - Primitivas core - especificacion detallada` for the
> framework's view of agent surfaces. If this file ever conflicts with the
> Brief, the Brief wins.

## What

`OpenAIProvider` is the second concrete subclass of `LLMProvider` (AJ-18).
It bridges the framework's vendor-agnostic wire types (`Message`, `Tool`,
`Response`, `Chunk`) to OpenAI's native Chat Completions API via the
official `openai` Python SDK.

This item delivers a minimal end-to-end OpenAI client good enough to:

- Make `@Agent(model="gpt-4o-mini")` and `@Agent(model="gpt-4o")` work end
  to end (tool use + streaming + embeddings).
- Be the embeddings provider that the rest of the framework (memory
  backends in AJ-24, eval datasets) routes to when an agent's primary
  provider — Anthropic — does not support embeddings natively.

## Why

Brief v4.0 §03 lists OpenAI as one of the four v0.1 native providers and
the universal embeddings answer for AJ-19's `AnthropicEmbeddingsNotSupportedError`.
AJ-18 set up the abstraction; AJ-19 filled the Anthropic slot; AJ-20 adds
OpenAI so the framework's claim of being vendor-agnostic stops being
theoretical. Once this lands the cross-provider fallback story in AJ-23
becomes exercisable end to end.

## Public surface (v0.1)

```python
from ajolopy.providers import LLMProvider, register_provider
from ajolopy.providers.openai import OpenAIProvider

# Already registered at import time:
#   register_provider("openai", OpenAIProvider)

# Default construction reads OPENAI_API_KEY from the env.
provider = OpenAIProvider()

# Explicit api_key — used by the framework bootstrap (AJ-14) when it
# forwards the value from ConfigService.
provider = OpenAIProvider(api_key="sk-...")

# Escape hatch: pre-built SDK client (custom timeout, base_url for
# Azure OpenAI through this provider, proxy, etc.).
import openai
provider = OpenAIProvider(client=openai.AsyncOpenAI(timeout=30))
```

### Constructor

```python
class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: openai.AsyncOpenAI | None = None,
    ) -> None: ...
```

Resolution order for the underlying client:

1. If `client` is provided, use it.
2. Else if `api_key` is provided, build `AsyncOpenAI(api_key=api_key)`.
3. Else if `OPENAI_API_KEY` is set in `os.environ`, build
   `AsyncOpenAI()` (the SDK reads the env var itself).
4. Otherwise raise `OpenAIConfigError("OPENAI_API_KEY missing — pass api_key=, client=, or set the env var")` at construction time.

The env-var fallback exists so the provider works standalone in scripts
and tests. The framework's bootstrap layer (AJ-14) will inject the
value from `ConfigService` (AJ-12) explicitly; application code should
never read `os.environ` directly.

## Design rules

- **Magical default**: `OpenAIProvider()` + `register_provider("openai", OpenAIProvider)` is enough for an `@Agent(model="gpt-…")` or `@Agent(model="o1-…")` to work.
- **Escape hatches**:
  - `client=` accepts a pre-built `AsyncOpenAI` for custom transport
    settings (timeout, proxy, base URL — including Azure OpenAI's
    tenant-specific URL, custom retries).
  - Subclass `OpenAIProvider` and override one of the public methods to
    extend behaviour (e.g. plug in structured outputs once `response_format`
    lands as a framework concept).
- **Embeddings are first-class.** `embed()` returns `list[list[float]]`
  whether the caller passes a single string or a list. The default
  embedding model when callers do not pass one is **not** hard-coded —
  the framework's bootstrap will route embed requests by model string
  (`text-embedding-3-small`, `text-embedding-3-large`) just like
  completions. Both routes already exist in `_DEFAULT_ROUTES`.

## Out of scope for this item

- `o1` / `o3` extended-thinking / `reasoning_effort` knobs — the SDK
  exposes them but their semantics differ enough from chat models that
  they deserve their own board item (a follow-up to AJ-28 / AJ-30).
- Structured outputs (`response_format=` with a Pydantic schema) — the
  *protocol* (forwarding `response_format` when the caller sets it on
  the SDK client) is in scope; framework-level ergonomics (`@Agent(output=Dto)`)
  are a separate item.
- Vision / image inputs — same as AJ-19, the wire `Message.content`
  stays `str` in v0.1.
- DALL·E / TTS / Whisper — not in the four v0.1 capabilities the
  framework claims to support.
- Pricing catalog → `AJ-30`.
- Cross-provider fallback declaration → `AJ-23`.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All tests mock the OpenAI SDK boundary; no real
network traffic happens in CI.

### Construction & registration

- [x] Importing `ajolopy.providers.openai` registers `OpenAIProvider`
      under the key `"openai"` in the registry.
- [x] `OpenAIProvider(api_key="sk-...")` constructs successfully and
      exposes an `AsyncOpenAI` instance internally.
- [x] `OpenAIProvider(client=<custom>)` uses the supplied client
      verbatim — no new `AsyncOpenAI` is built.
- [x] `OpenAIProvider()` with `OPENAI_API_KEY` set in the env builds a
      client successfully (no error).
- [x] `OpenAIProvider()` with `OPENAI_API_KEY` unset raises
      `OpenAIConfigError` at construction time, naming the env var.

### `complete()`

- [x] A simple `complete(model="gpt-4o-mini", messages=[…])` call proxies
      to `client.chat.completions.create(...)` and returns a `Response`
      with `text`, `tokens_in`, `tokens_out`, `finish_reason="stop"`.
- [x] Messages with `role="system"` are forwarded as a leading
      `{"role": "system", ...}` entry in the `messages` array (OpenAI
      does not have a separate top-level field).
- [x] `tools=[Tool(...)]` is converted to OpenAI's function-calling
      schema (`{"type": "function", "function": {...}}`) and forwarded;
      if the response includes a `tool_calls` entry, the returned
      `Response.tool_calls` contains the corresponding `ToolCall`.
- [x] `temperature` / `max_tokens` are forwarded as-is to the SDK.
- [x] OpenAI's automatic prompt caching applies to system + first-user
      messages once the prompt crosses the SDK's documented threshold;
      `cache=True` is accepted but a no-op (OpenAI does not require an
      opt-in flag). Verified by asserting the SDK was called without an
      extra cache kwarg leaking through.
- [x] A retriable SDK error (`openai.APIConnectionError` /
      `openai.APITimeoutError` / `openai.RateLimitError`) surfaces as a
      typed `OpenAIProviderError` rather than the raw SDK exception.

### `stream()`

- [x] `stream(model="gpt-4o-mini", messages=[…])` returns an async
      iterator that yields `Chunk(delta=…)` for each text delta.
- [x] The final `Chunk` carries `finish_reason="stop"` (or the mapped
      equivalent).
- [x] Cancelling the iterator mid-stream cancels the underlying SDK
      stream (no orphan HTTP connections in test).
- [x] Tool-call deltas (OpenAI's `delta.tool_calls[...]`) are surfaced
      as `Chunk.tool_call_delta`, accumulating across chunks the way
      the SDK emits them (`{"index": N, "function": {"arguments": "..."}}`).

### `embed()`

- [x] `embed(model="text-embedding-3-small", text="hello")` proxies to
      `client.embeddings.create(...)` and returns `list[list[float]]`
      with one inner list (the single vector).
- [x] `embed(model="text-embedding-3-small", text=["a", "b"])` returns
      two vectors in input order.
- [x] Empty `text=[]` returns `[]` without calling the SDK.

### `count_tokens()`

- [x] `count_tokens(model="gpt-4o-mini", text="hello")` returns a
      deterministic integer (≥ 1). Use `tiktoken` when the encoding is
      known; fall back to a `len(text) // 4` estimate and log a warning
      otherwise.
- [x] `count_tokens(model="o1-preview", text="hello")` works for the
      reasoning-model series (their encoding is the same as `gpt-4o`).

### Capability flags

- [x] `supports_prompt_caching()` returns `True` (OpenAI caches
      automatically; the framework reports the capability so callers
      can rely on the feature).
- [x] `supports_tool_calling()` returns `True`.

### Negative cases

- [x] A non-OpenAI model string (`model="claude-opus-4-7"`) passed to
      any method raises `OpenAIProviderError` with the offending model
      in the message. (The router would normally prevent this, but the
      provider double-checks so subclasses cannot silently route the
      wrong model.)
- [x] A finish reason the SDK can emit but the framework's
      `FinishReason` literal does not know about (`"function_call"`
      legacy, `"content_filter"`) maps to `"stop"` and logs a warning.

## Implementation pointers

- Source: `src/ajolopy/providers/openai/`.
  - `provider.py` — `OpenAIProvider` class.
  - `errors.py` — `OpenAIProviderError`, `OpenAIConfigError`.
  - `__init__.py` — public exports + `register_provider("openai", OpenAIProvider)`.
- Tests: `tests/providers/openai/`. All SDK calls mocked via
  `unittest.mock.AsyncMock` patching `openai.AsyncOpenAI.chat.completions`
  and `openai.AsyncOpenAI.embeddings`.
- Runtime deps to add via `uv add`: `openai` (the official Python SDK,
  Apache-2.0). PR description must justify the addition (matches the
  Brief's v0.1 multi-provider non-negotiable) and confirm no known
  CVEs against the pinned version.
- Optional dev/runtime dep: `tiktoken` (MIT) for offline token counts.
  Add via `uv add` with a clear justification in the PR description —
  `tiktoken` ships pre-built wheels for all supported platforms so it
  does not add a compiler dependency.

## Implementation notes

Scope decisions taken while shipping AJ-20:

- **Model-prefix allowlist.** The defence-in-depth check in
  `_ensure_openai_model` accepts `gpt-`, `o1-`, `o3-`, `text-embedding-`,
  and `chatgpt-`. Any new family (`o4-`, `gpt-5-*`) needs an explicit
  entry — the registry already covers these prefixes via
  `_DEFAULT_ROUTES`, so the provider's allowlist stays in sync without
  shipping a separate catalog.
- **`cache=True` is intentionally a no-op.** OpenAI applies prompt
  caching automatically once a request crosses the SDK threshold (~1024
  tokens); there is no opt-in flag to forward. The test
  `test_cache_true_is_no_op_no_extra_kwargs` asserts the SDK call shape
  is identical between `cache=True` and `cache=False`. The capability
  flag `supports_prompt_caching()` still returns `True` so the framework
  can advertise the feature.
- **`max_tokens` is forwarded only when set.** Unlike Anthropic (which
  requires the field), OpenAI accepts no value and uses the model
  default. Inventing a default here would be a silent ceiling on every
  call — callers can pass it explicitly when they want one.
- **`count_tokens` is sync + `tiktoken`-only.** OpenAI does not ship an
  online token-count endpoint, so the implementation skips the SDK call
  entirely. `tiktoken.encoding_for_model` covers `gpt-4o*`, `o1*`, `o3*`
  via the same `o200k_base` tokenizer, plus the legacy chat models;
  any model `tiktoken` does not know falls back to a deterministic
  `len(text) // 4` estimate with a warning logged to
  `ajolopy.providers.openai`.
- **Tool-call arguments are decoded eagerly.** OpenAI delivers the
  arguments as a JSON-encoded string; the provider parses them into a
  `dict[str, Any]` before populating `ToolCall.arguments`. Non-JSON
  payloads (rare, but possible during malformed streaming) are captured
  under `{"_raw": <string>}` plus a warning so the conversation history
  stays consistent and the model can recover on its own.
- **Stream events can carry both text and tool-call deltas.** The
  `_convert_stream_event` helper returns a list of `Chunk` objects so a
  single SDK `ChatCompletionChunk` can emit multiple wire-level chunks
  in the order they arrive (text first, tool-call deltas next, terminal
  `finish_reason` last). This matches OpenAI's documented streaming
  semantics and keeps the consumer pattern identical to Anthropic's.
- **Early-cancellation safety.** `stream()`'s generator has a `finally`
  block that calls `close()` on the SDK stream object (best-effort,
  await it if the result is awaitable). This prevents orphan HTTP
  sockets when the caller breaks out of the iterator before draining
  it; the test `test_stream_cancellation_closes_underlying_sdk_stream`
  pins the behaviour.
- **Embeddings short-circuit on empty input.** `embed(model=..., text=[])`
  returns `[]` immediately without an SDK call. This protects callers
  that do `embed(model, list(iterator))` against burning a roundtrip
  for an empty batch.
- **`embed()` reuses the model-prefix guard.** Passing a Claude model
  to `embed()` raises `OpenAIProviderError` for the same defence-in-depth
  reason as `complete()` / `stream()` — the spec only required the
  guard on completion paths, but extending it to embeddings is cheap
  and removes the only call site without the check.
