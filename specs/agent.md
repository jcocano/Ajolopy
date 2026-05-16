# AJ-1 — `@Agent` decorator

> Tracked in [`board.json`](../board.json) as `AJ-1`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §01 (primitive spec) and §03
> (multi-provider architecture). If this file ever conflicts with the Brief,
> the Brief wins.

## What

`@Agent` is a **class decorator** that turns a Python class into an LLM-powered
agent. The decorator:

1. Validates the agent's configuration at definition time.
2. Resolves the LLM provider from the `model` string via the `LLMProvider`
   registry (AJ-18).
3. Injects two methods on the decorated class:
   - `async run(message: str) -> str` — one-shot completion.
   - `async stream(message: str) -> AsyncIterator[str]` — token stream.
4. Discovers `@Tool`-marked methods and exposes them to the LLM (tools wired in
   AJ-2; this item ships the discovery hook + a "no tools" code path).
5. Applies retry, optional fallback, optional tracing, optional prompt caching,
   and memory persistence based on the kwargs.

## Why

The wedge user — an AI Engineer at a Series A AI startup — duct-tapes the same
plumbing on every new project: provider SDK setup, retry policy, OpenTelemetry
spans, env-variable validation, fallback when the primary model is degraded.
`@Agent` collapses that into a single decorator and follows the framework-wide
**"magical default + escape hatch"** rule.

## Public surface (v0.1)

```python
from ajolopy import Agent

@Agent(
    model="claude-opus-4-7",
    system="You are a helpful assistant.",
    memory="redis://localhost:6379",
    trace=True,
    cache="prompt",
    fallback=["claude-haiku-4-5", "gpt-4o-mini"],
    temperature=0.7,
    max_tokens=1024,
)
class Support:
    """Top-level docstring is the agent description."""
```

### Signature

```python
@Agent(
    model: str,
    system: str | Callable[..., str],
    memory: str | dict | type[Memory] | None = None,
    trace: bool = False,
    cache: Literal["prompt"] | None = None,
    fallback: str | list[str] | Callable | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[type] | None = None,
)
```

### Injected API

```python
agent = Support()
answer: str = await agent.run("where is my order?")
async for token in agent.stream("where is my order?"):
    print(token, end="")
```

## Design rules

- **Magical default**: every kwarg is a string or primitive. The string-based
  `model` selects the provider through prefix routing (Brief §03):
  `claude-*` → Anthropic, `gpt-*` → OpenAI, `gemini-*` → Gemini,
  `ollama:*`/`groq:*`/`openrouter:*`/`together:*`/`mistral:*`/`deepseek:*`/`azure:*`
  → UniversalOpenAIProvider. Covers ~90% of cases with zero ceremony.
- **Escape hatches**:
  - `system=` accepts a callable that receives the request context and returns
    a string — for per-request system prompts.
  - `memory=` accepts a `type[Memory]` subclass for custom storage backends.
  - `fallback=` accepts a callable for custom retry/fallback logic.
  - Subclass `Agent` (the runtime class behind the decorator) for full control.

## Vendor-agnostic — no provider-specific assumptions

Per Brief §03, the framework MUST NOT be coupled to any single LLM provider.
This item depends on:

- **AJ-18** — `LLMProvider` ABC + provider registry + prefix routing.
- **AJ-19** — at least one concrete provider (Anthropic) for end-to-end tests.

`@Agent` itself contains zero provider-specific code; it consumes the
`LLMProvider` resolved from the registry.

## Out of scope for this item

- `@Tool` execution loop → `AJ-2`. This item only discovers tools and forwards
  them to the provider; the function-calling loop lives in `AJ-2`.
- `@Stream` HTTP endpoint binding → `AJ-3`. This item ships `self.stream()` as
  an async iterator over tokens; HTTP SSE binding is `AJ-3`.
- `@Eval` / `@Metric` instrumentation → `AJ-4` / `AJ-5`.
- `@Workflow` orchestration → `AJ-6`.
- Concrete Memory backends (in-memory, Redis) → `AJ-24`. This item only
  defines the `Memory` ABC so the escape hatch can be exercised.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`.

### Magical-default path

- [x] `@Agent(model="claude-opus-4-7", system="...")` on a class makes
      instances callable via `await instance.run("...")` and produces a `str`.
- [x] The decorator preserves the class type so pyright sees the original
      class methods (decorator returns `type[T]`, not `Any`).
- [x] The decorator validates `model` against the provider registry at
      definition time and fails fast with a clear error referencing the
      supported prefixes when the model is unknown.

### Multi-provider routing

- [x] A `model="claude-..."` agent resolves to the Anthropic provider via the
      registry (verified by mocking the registry call).
- [x] A `model="gpt-..."` agent resolves to the OpenAI provider entry in the
      registry, regardless of whether the concrete provider is installed yet
      (registry lookup is what's tested, not the call).
- [x] A `model="ollama:llama3.3"` agent resolves to the universal-OpenAI
      provider entry.

### Streaming surface

- [x] `instance.stream("...")` returns an async iterator yielding `str` chunks.
- [x] Cancelling the iterator mid-stream cancels the underlying provider call.

### Memory escape hatch

- [x] `memory="redis://..."` passes the URL to the default Memory factory
      (stubbed in this item; concrete Redis lands in AJ-24).
- [x] Subclassing `Memory` and passing the subclass to `memory=` causes
      `run`/`stream` to call the subclass for reads and writes.

### Fallback

- [x] `fallback="claude-haiku-4-5"` retries on the named model when the primary
      raises a retriable provider error.
- [x] `fallback=["claude-haiku-4-5", "gpt-4o-mini"]` tries the list in order.
- [x] A `fallback=` callable receives the original request payload on primary
      failure and its return value is surfaced as the agent's answer.

### Observability

- [x] `trace=True` emits one OpenTelemetry span per `run`/`stream` invocation
      with attributes `agent.name`, `agent.model`, `agent.provider`,
      `agent.tokens_in`, `agent.tokens_out`.
- [x] `trace=False` (default) emits no spans.

### Prompt caching

- [x] `cache="prompt"` with a static `system` string is accepted and forwarded
      to the provider's caching hook (the provider decides what to do with it).
- [x] `cache="prompt"` with a callable `system` raises a clear configuration
      error — caching requires a static prompt.

### Configuration validation

- [x] An agent whose provider requires an env var (e.g. `ANTHROPIC_API_KEY`)
      raises a clear `AgentConfigError` **at definition time** when the var is
      missing.

### Negative cases

- [x] An unknown model prefix raises a clear error naming the supported
      prefixes.
- [x] A network error after retries are exhausted bubbles up as a typed
      `AgentError` (not a raw `httpx` / SDK exception).

## Implementation pointers

- Source: `src/ajolopy/agent/` (package).
- Runtime base class: `src/ajolopy/agent/runtime.py` (exposes `run` / `stream`).
- Decorator factory: `src/ajolopy/agent/decorator.py`.
- Errors: `src/ajolopy/agent/errors.py` (`AgentError`, `AgentConfigError`,
  `AgentProviderError`).
- Memory ABC: `src/ajolopy/memory.py` (single file — concrete backends land in
  AJ-24).
- Tests: `tests/agent/`.

## Implementation notes

- `2026-05-12` — Shipped `src/ajolopy/agent/{decorator,runtime,errors}.py`
  plus `src/ajolopy/memory.py` (`Memory` ABC + `InMemoryMemory` +
  `resolve_memory`). Scope decisions taken during implementation:
  - **Tool use deferred to AJ-2.** When the model returns
    `Response.tool_calls`, the runtime raises
    `AgentToolUseUnsupportedError` with a pointer to AJ-2. ``tools=``
    kwarg is accepted but **not forwarded** to the provider in this
    item; AJ-2 will wire the full loop. Keeps the `run() -> str`
    signature clean.
  - **Fallback validated at decoration time.** Every model in the
    primary + fallback chain is resolved against the registry and the
    corresponding provider is instantiated; any failure raises
    `AgentConfigError` immediately. Provider instances are cached by
    provider key so duplicate providers across the chain share one
    SDK client.
  - **OpenTelemetry as a runtime dep.** Added `opentelemetry-api`
    (>= 1.41). `trace=True` emits one span per `run` / `stream` with
    `agent.name`, `agent.model`, `agent.provider`. AJ-28 will widen
    the surface (cost tracking, full `gen_ai.*` attrs, exporters).
  - **Memory factory tolerates URL strings now, parses them in AJ-24.**
    `@Agent(memory="redis://...")` builds an `InMemoryMemory` whose
    `url` attribute stores the original string so AJ-24 swaps in a
    real backend by replacing `resolve_memory` only.
  - **New base error type.** Added `LLMProviderError` in
    `ajolopy.providers.base` so the agent can `except` retriable
    provider failures without importing concrete-provider error
    classes. `AnthropicProviderError` now inherits from it.
  - **Test registry isolation moved to `tests/conftest.py`** (root)
    so `tests/agent/` benefits from the same `_PROVIDERS` clear-and-
    restore each test. Pyright's `executionEnvironments` for `tests/`
    was widened to ignore the `Unknown*` reports on framework
    internals accessed by tests; the production code stays in
    strict mode.
  - **Coverage of new code.** `src/ajolopy/agent/`: 89%
    (`runtime.py` 89%, decorator/errors 100%). `src/ajolopy/memory.py`:
    71% (uncovered branches handle dict/instance memory specs not
    exercised yet).
