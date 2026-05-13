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

- [ ] Importing `ajolopy.providers.openai` registers `OpenAIProvider`
      under the key `"openai"` in the registry.
- [ ] `OpenAIProvider(api_key="sk-...")` constructs successfully and
      exposes an `AsyncOpenAI` instance internally.
- [ ] `OpenAIProvider(client=<custom>)` uses the supplied client
      verbatim — no new `AsyncOpenAI` is built.
- [ ] `OpenAIProvider()` with `OPENAI_API_KEY` set in the env builds a
      client successfully (no error).
- [ ] `OpenAIProvider()` with `OPENAI_API_KEY` unset raises
      `OpenAIConfigError` at construction time, naming the env var.

### `complete()`

- [ ] A simple `complete(model="gpt-4o-mini", messages=[…])` call proxies
      to `client.chat.completions.create(...)` and returns a `Response`
      with `text`, `tokens_in`, `tokens_out`, `finish_reason="stop"`.
- [ ] Messages with `role="system"` are forwarded as a leading
      `{"role": "system", ...}` entry in the `messages` array (OpenAI
      does not have a separate top-level field).
- [ ] `tools=[Tool(...)]` is converted to OpenAI's function-calling
      schema (`{"type": "function", "function": {...}}`) and forwarded;
      if the response includes a `tool_calls` entry, the returned
      `Response.tool_calls` contains the corresponding `ToolCall`.
- [ ] `temperature` / `max_tokens` are forwarded as-is to the SDK.
- [ ] OpenAI's automatic prompt caching applies to system + first-user
      messages once the prompt crosses the SDK's documented threshold;
      `cache=True` is accepted but a no-op (OpenAI does not require an
      opt-in flag). Verified by asserting the SDK was called without an
      extra cache kwarg leaking through.
- [ ] A retriable SDK error (`openai.APIConnectionError` /
      `openai.APITimeoutError` / `openai.RateLimitError`) surfaces as a
      typed `OpenAIProviderError` rather than the raw SDK exception.

### `stream()`

- [ ] `stream(model="gpt-4o-mini", messages=[…])` returns an async
      iterator that yields `Chunk(delta=…)` for each text delta.
- [ ] The final `Chunk` carries `finish_reason="stop"` (or the mapped
      equivalent).
- [ ] Cancelling the iterator mid-stream cancels the underlying SDK
      stream (no orphan HTTP connections in test).
- [ ] Tool-call deltas (OpenAI's `delta.tool_calls[...]`) are surfaced
      as `Chunk.tool_call_delta`, accumulating across chunks the way
      the SDK emits them (`{"index": N, "function": {"arguments": "..."}}`).

### `embed()`

- [ ] `embed(model="text-embedding-3-small", text="hello")` proxies to
      `client.embeddings.create(...)` and returns `list[list[float]]`
      with one inner list (the single vector).
- [ ] `embed(model="text-embedding-3-small", text=["a", "b"])` returns
      two vectors in input order.
- [ ] Empty `text=[]` returns `[]` without calling the SDK.

### `count_tokens()`

- [ ] `count_tokens(model="gpt-4o-mini", text="hello")` returns a
      deterministic integer (≥ 1). Use `tiktoken` when the encoding is
      known; fall back to a `len(text) // 4` estimate and log a warning
      otherwise.
- [ ] `count_tokens(model="o1-preview", text="hello")` works for the
      reasoning-model series (their encoding is the same as `gpt-4o`).

### Capability flags

- [ ] `supports_prompt_caching()` returns `True` (OpenAI caches
      automatically; the framework reports the capability so callers
      can rely on the feature).
- [ ] `supports_tool_calling()` returns `True`.

### Negative cases

- [ ] A non-OpenAI model string (`model="claude-sonnet-4-7"`) passed to
      any method raises `OpenAIProviderError` with the offending model
      in the message. (The router would normally prevent this, but the
      provider double-checks so subclasses cannot silently route the
      wrong model.)
- [ ] A finish reason the SDK can emit but the framework's
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

_Populated as the item is implemented._
