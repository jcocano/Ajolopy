# AJ-19 — `AnthropicProvider`

> Tracked in [`board.json`](../board.json) as `AJ-19`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §03 (multi-provider — Anthropic
> entry) plus `01 - Primitivas core - especificacion detallada` for the
> framework's view of agent surfaces. If this file ever conflicts with the
> Brief, the Brief wins.

## What

`AnthropicProvider` is the first concrete subclass of `LLMProvider` (AJ-18).
It bridges the framework's vendor-agnostic wire types (`Message`, `Tool`,
`Response`, `Chunk`) to Anthropic's native Messages API via the official
`anthropic` Python SDK.

This item delivers a minimal end-to-end Anthropic client good enough to:

- Drive the killer-demo Paso 1 (`@Agent` + `@Stream` against Anthropic).
- Unblock `AJ-1` (`@Agent`) — once this item ships, AJ-1's last blocker is met.

## Why

Brief v4.0 §03 lists Anthropic as one of the four v0.1 native providers, the
preferred-for-defaults provider per the author, and the target of the killer
demo's Paso 1. AJ-18 set up the abstraction; AJ-19 fills it with the first
working implementation so the abstraction is exercised, not just declared.

## Public surface (v0.1)

```python
from ajolopy.providers import LLMProvider, register_provider
from ajolopy.providers.anthropic import AnthropicProvider

# Already registered at import time:
#   register_provider("anthropic", AnthropicProvider)

# Default construction reads ANTHROPIC_API_KEY from the env.
provider = AnthropicProvider()

# Explicit api_key — used by the framework bootstrap (AJ-14) when it
# forwards the value from ConfigService.
provider = AnthropicProvider(api_key="sk-ant-...")

# Escape hatch: pre-built SDK client (custom timeout, proxy, base_url, etc.).
import anthropic
provider = AnthropicProvider(client=anthropic.AsyncAnthropic(timeout=30))
```

### Constructor

```python
class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None: ...
```

Resolution order for the underlying client:

1. If `client` is provided, use it.
2. Else if `api_key` is provided, build `AsyncAnthropic(api_key=api_key)`.
3. Else if `ANTHROPIC_API_KEY` is set in `os.environ`, build
   `AsyncAnthropic()` (the SDK reads the env var itself).
4. Otherwise raise `AnthropicConfigError("ANTHROPIC_API_KEY missing — pass api_key=, client=, or set the env var")` at construction time.

The env-var fallback exists so the provider works standalone in scripts /
tests. The framework's bootstrap layer (AJ-14) will inject the value from
`ConfigService` (AJ-12) explicitly; application code should never read
`os.environ` directly.

## Design rules

- **Magical default**: `AnthropicProvider()` + `register_provider("anthropic", AnthropicProvider)` is enough for an `@Agent(model="claude-…")` to work.
- **Escape hatches**:
  - `client=` accepts a pre-built `AsyncAnthropic` for custom transport
    settings (timeout, proxy, base URL, retries).
  - Subclass `AnthropicProvider` and override one of the public methods to
    extend behaviour (e.g. plug in extended thinking once that lands).

## Out of scope for this item

- `embed()` — Anthropic does not ship native text embeddings. The method
  raises a typed `AnthropicEmbeddingsNotSupportedError` so callers fail with
  a clear message and route through a different provider (OpenAI's
  `text-embedding-3-*`).
- Tool-calling loop — the *protocol* (passing `tools=[...]`, returning
  `Response.tool_calls`, streaming `tool_call_delta`) is in scope. The
  *loop* that executes tools and feeds results back into the model is
  `AJ-2`'s territory.
- Extended thinking / reasoning effort knobs — Brief lists them as future.
- Vision / PDFs — same. The wire `Message.content` stays `str` in v0.1.
- Pricing catalog → `AJ-30`.
- Cross-provider fallback declaration → `AJ-23`.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All tests mock the Anthropic SDK boundary; no real
network traffic happens in CI.

### Construction & registration

- [x] Importing `ajolopy.providers.anthropic` registers
      `AnthropicProvider` under the key `"anthropic"` in the registry.
- [x] `AnthropicProvider(api_key="sk-...")` constructs successfully and
      exposes an `AsyncAnthropic` instance internally.
- [x] `AnthropicProvider(client=<custom>)` uses the supplied client
      verbatim — no new `AsyncAnthropic` is built.
- [x] `AnthropicProvider()` with `ANTHROPIC_API_KEY` set in the env builds
      a client successfully (no error).
- [x] `AnthropicProvider()` with `ANTHROPIC_API_KEY` unset raises
      `AnthropicConfigError` at construction time, naming the env var.

### `complete()`

- [x] A simple `complete(model="claude-opus-4-7", messages=[…])` call
      proxies to `client.messages.create(...)` and returns a `Response`
      with `text`, `tokens_in`, `tokens_out`, `finish_reason="stop"`.
- [x] Messages with `role="system"` are forwarded as the Anthropic
      top-level `system` parameter — not as a `messages[]` entry.
- [x] `tools=[Tool(...)]` is converted to Anthropic's tool schema and
      forwarded; if the response includes a `tool_use` content block, the
      returned `Response.tool_calls` contains the corresponding
      `ToolCall`.
- [x] `temperature` / `max_tokens` are forwarded as-is to the SDK.
- [x] `cache=True` annotates the system message with
      `cache_control={"type": "ephemeral"}` so prompt caching is enabled.
- [x] A retriable SDK error (`anthropic.APIConnectionError` /
      `anthropic.APITimeoutError`) surfaces as a typed
      `AnthropicProviderError` rather than the raw SDK exception.

### `stream()`

- [x] `stream(model="claude-opus-4-7", messages=[…])` returns an async
      iterator that yields `Chunk(delta=…)` for each text delta.
- [x] The final `Chunk` carries `finish_reason="stop"` (or the mapped
      equivalent).
- [x] Cancelling the iterator mid-stream cancels the underlying SDK
      stream (no orphan HTTP connections in test).
- [x] Tool-use deltas are surfaced as `Chunk.tool_call_delta`.

### `embed()`

- [x] `embed(model="claude-…", text="…")` raises
      `AnthropicEmbeddingsNotSupportedError` with a message pointing users
      to an embeddings-capable provider.

### `count_tokens()`

- [x] `count_tokens(model="claude-opus-4-7", text="hello")` returns the
      value reported by the SDK's count-tokens endpoint when available.
- [x] If the SDK call fails or the endpoint is unreachable, the method
      falls back to a deterministic 4-chars-per-token estimate and logs
      a warning (verified with `caplog`).

### Capability flags

- [x] `supports_prompt_caching()` returns `True`.
- [x] `supports_tool_calling()` returns `True`.

### Negative cases

- [x] A non-Claude model string (`model="gpt-4o-mini"`) passed to any
      method raises `AnthropicProviderError` with the offending model in
      the message. (The router would normally prevent this, but the
      provider double-checks so subclasses cannot silently route the
      wrong model.)

## Implementation pointers

- Source: `src/ajolopy/providers/anthropic/`.
  - `provider.py` — `AnthropicProvider` class.
  - `errors.py` — `AnthropicProviderError`,
    `AnthropicConfigError`,
    `AnthropicEmbeddingsNotSupportedError`.
  - `__init__.py` — public exports + `register_provider("anthropic", AnthropicProvider)`.
- Tests: `tests/providers/anthropic/`. All SDK calls mocked via
  `unittest.mock.AsyncMock` patching `anthropic.AsyncAnthropic.messages`.
- Runtime dep to add via `uv add`: `anthropic` (the official Python SDK,
  MIT-licensed).

## Implementation notes

- `2026-05-12` — Shipped `src/ajolopy/providers/anthropic/{provider,errors,__init__}.py`
  with `anthropic` (SDK 0.101.0) as a new runtime dep. The package import
  registers `AnthropicProvider` under the `"anthropic"` key via
  `contextlib.suppress(ValueError)` so the second import inside the same
  process is a no-op. Mapped Anthropic's `stop_reason` values to the
  framework's `FinishReason` literal (`end_turn`/`stop_sequence`→`stop`,
  `max_tokens`→`length`, `tool_use`→`tool_calls`). `count_tokens` is sync
  per the ABC but the SDK's endpoint is async; the provider runs
  `asyncio.run` when no loop is active and falls back to a deterministic
  4-chars-per-token estimate (with a `logging.WARNING`) when it is or when
  the SDK call fails. Updated `tests/providers/conftest.py` so the parent
  `isolate_registry` fixture *clears* `_PROVIDERS` at the start of each
  test (instead of just restoring it at the end) — keeps tests
  order-independent now that some importable provider packages have
  registration side effects.
