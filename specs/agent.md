# AJ-1 — `@Agent` decorator

> Tracked in [`board.json`](../board.json) as `AJ-1`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.

## What

The `@Agent` decorator turns a Python function into an LLM-powered agent.
Calling the decorated function performs the LLM invocation with retries,
tracing, environment validation, and optional fallback handled by the decorator.

## Why

The wedge user — an AI Engineer at a Series A AI startup — duct-tapes together
the same plumbing on every new project: client setup, retry policy,
OpenTelemetry tracing, environment-variable validation, and provider fallback.
`@Agent` collapses that into a single decorator that follows the framework-wide
**"magical default + escape hatch"** rule.

## Public surface (v0.1)

```python
from ajolopy import Agent

@Agent(
    model="claude-sonnet-4-6",
    memory="redis://localhost:6379",
    trace=True,
    fallback="claude-haiku-4-5",
)
def support(question: str) -> str: ...
```

## Design rule

- **Magical default**: every kwarg is a string (`model`, `memory`, `fallback`).
  Covers ~90% of cases with zero ceremony.
- **Escape hatch**: subclass `Memory` for custom storage; pass a callable for
  custom retry/fallback logic; subclass `Agent` for full control.

## Out of scope for this item

- Multi-provider routing → separate board item (tracked when added).
- Tool calling loop → `AJ-2` (`@Tool`).
- Streaming → `AJ-3` (`@Stream`).
- Eval / metric instrumentation → `AJ-4` (`@Eval`) / `AJ-5` (`@Metric`).

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`.

### Magical-default path

- [ ] `@Agent(model="claude-sonnet-4-6")` on a sync function returns a callable
      that produces a `str` answer when invoked.
- [ ] The decorator preserves the wrapped function's signature so pyright sees
      the original parameter and return types at call sites.
- [ ] Calling the agent without `ANTHROPIC_API_KEY` set fails with an
      actionable error message **at startup** (not at first invocation).

### Escape-hatch path

- [ ] Subclassing `Memory` and passing the subclass to `memory=` uses the
      subclass for all reads/writes (verified with a mock).
- [ ] Passing a `fallback=` callable instead of a model-name string invokes the
      callable on primary-model failure with the original request payload.

### Observability

- [ ] `trace=True` emits one OpenTelemetry span per agent invocation with
      attributes `agent.name`, `agent.model`, `agent.tokens_in`,
      `agent.tokens_out`.
- [ ] When `trace=False` (default), no span is emitted.

### Async surface

- [ ] `@Agent(...)` applied to an `async def` function returns an awaitable
      that produces a `str` answer.

### Negative cases

- [ ] Invalid model name (e.g. `model="bogus"`) fails fast with a clear message
      referencing the supported models for the active provider.
- [ ] Network error after retries are exhausted bubbles up as a typed
      `AgentError` (not a raw `httpx` exception).

## Implementation pointers

- Source: `src/ajolopy/agent/` (TBD)
- Tests: `tests/agent/` (TBD)
- Provider in v0.1: Anthropic only. Multi-provider abstraction lands later as a
  separate board item.

## Implementation notes

Empty for now. Append entries during the work in chronological order with a
`YYYY-MM-DD` prefix.
