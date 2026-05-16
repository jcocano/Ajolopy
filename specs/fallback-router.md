# AJ-23 — Cross-provider fallback declarativo (observability + workflow + docs)

> Tracked in [`board.json`](../board.json) as `AJ-23`. AJ-1 already shipped the
> `fallback=` kwarg + provider chain validation. AJ-23 closes the gap on
> observability, extends fallback to `@Workflow` coordinators, and locks
> the contract with cross-provider integration tests + docs.

## What

Three additions on top of AJ-1's existing fallback:

1. **OTel instrumentation** for each fallback transition. The agent
   runtime already loops through `self._models` on `LLMProviderError`;
   AJ-23 emits a `chat.fallback {from→to}` event (or attributes on
   the next chat span) recording the transition.
2. **`@Workflow(coordinator_fallback=[...])`** kwarg. The workflow's
   coordinator LLM gets a fallback chain analogous to `@Agent`.
   Validated at decoration time through the same provider registry.
3. **Cross-provider integration tests + docs**. A fake-provider test
   matrix verifies anthropic→openai, openai→gemini, etc.

## Why

Brief v4.0 §"7 dolores ancla" dolor #5: "Anthropic outage = app caída
→ `fallback=[\"claude-haiku-4-5\", \"gpt-4o-mini\"]` cross-provider en el
decorator". The `fallback=` kwarg is already there (AJ-1) but
observable proof of WHICH model handled the request requires the
transition event AJ-23 ships.

## Public surface (v0.1)

### `@Agent` — unchanged signature

`fallback=` already exists. AJ-23 adds NO new kwarg here. Behavior
unchanged, observability richer.

### `@Workflow(coordinator_fallback=[...])` — new kwarg

```python
@Workflow(
    coordinator="claude-opus-4-7",
    coordinator_fallback=["claude-haiku-4-5", "gpt-4o-mini"],
    agents=[Triage, Billing],
)
class Team: ...
```

Same semantics as `@Agent(fallback=...)`. Validated at decoration time
(every model resolves through the registry). When the coordinator's
chat call raises `LLMProviderError`, the runtime tries the next model
in the chain. Each transition emits the same `chat.fallback` event.

### Observability surface

For each fallback transition (within `@Agent` OR `@Workflow`
coordinator), the framework records ONE span event on the **next**
chat span:

- Event name: `gen_ai.chat.fallback`
- Attributes:
  - `ajolopy.fallback.from`: the failing model string (`"claude-opus-4-7"`)
  - `ajolopy.fallback.from_provider`: the provider key (`"anthropic"`)
  - `ajolopy.fallback.to`: the next model string (`"gpt-4o-mini"`)
  - `ajolopy.fallback.to_provider`: the next provider key (`"openai"`)
  - `ajolopy.fallback.reason`: `str(exception)` truncated to 200 chars

The transition event sits on the new `chat` span (NOT the failed one),
so trace viewers naturally show "model X failed → model Y was used".

NEW constants in `ajolopy.observability.conventions`:
- `AJOLOPY_FALLBACK_FROM`
- `AJOLOPY_FALLBACK_FROM_PROVIDER`
- `AJOLOPY_FALLBACK_TO`
- `AJOLOPY_FALLBACK_TO_PROVIDER`
- `AJOLOPY_FALLBACK_REASON`
- `GEN_AI_CHAT_FALLBACK_EVENT = "gen_ai.chat.fallback"`

## Cross-cuts

### AJ-1 (`AgentRuntime`) — additive
- `_run_tool_loop` / `_stream_tool_loop` already iterate `self._models`.
  AJ-23 adds an `_emit_fallback_event(span, from_model, to_model, reason)`
  helper that the outer `for` loop calls after catching
  `LLMProviderError` and BEFORE the next iteration.

### AJ-6 (`@Workflow`) — additive
- `WorkflowMetadata` gains `coordinator_fallback: tuple[str, ...]`.
- `WorkflowRuntime` resolves and instantiates each fallback model at
  decoration time (mirrors the agent's chain validation).
- Coordinator chat loop in `WorkflowRuntime` mirrors `AgentRuntime`'s
  fallback loop: on `LLMProviderError`, advance to the next coordinator
  model in the chain, emit the fallback event.

### AJ-28 (observability conventions) — additive
- 6 new attribute constants + event name.

## Out of scope

- New `fallback=` kwarg surfaces (none — AJ-1's stays).
- Retry policies / backoff (`LLMProviderError` is the only trigger;
  no smart retry of the SAME model).
- Provider-aware fallback ordering (e.g., "always try openai before
  gemini") — order follows the user-supplied list literally.

## Acceptance criteria

### Observability

- [ ] An `@Agent(fallback=[...])` whose primary fails with
      `LLMProviderError` and whose secondary succeeds produces ONE
      `gen_ai.chat.fallback` event on the secondary's `chat` span
      with the 5 documented attributes.
- [ ] The reason attribute is truncated to ≤200 chars.
- [ ] Two consecutive failures (primary → secondary → tertiary)
      produce TWO fallback events on the tertiary's chat span.
- [ ] Successful primary call → no fallback events anywhere.
- [ ] Fallback event fires for both `run()` and `stream()` paths.

### `@Workflow.coordinator_fallback`

- [ ] `@Workflow(coordinator="...", coordinator_fallback=["..."])`
      validates the chain at decoration time; unknown model in the
      chain → `WorkflowConfigError`.
- [ ] Coordinator's first call fails → next model is invoked. Event
      fires on the next coordinator-turn chat span.
- [ ] All coordinator models exhausted → `WorkflowError` (or matching
      coordinator-failure pathway from AJ-6).
- [ ] `coordinator_fallback` is ignored when `route()` is overridden
      (the override path doesn't use a coordinator chat).

### Cross-provider integration tests

- [ ] Mock provider matrix: anthropic-primary fails → openai-fallback
      succeeds → final response is from openai with proper events.
- [ ] openai-primary fails → gemini-fallback succeeds.
- [ ] Test asserts `_models[i]` instantiation happens only once per
      provider key (validates the existing provider cache).

### Docs

- [ ] README section: "Cross-provider fallback" with example +
      explanation of the OTel trace shape.
- [ ] `specs/agent.md` Implementation notes get a bullet pointing at
      AJ-23 for the observability extension.

## Implementation pointers

- `src/ajolopy/agent/runtime.py`:
  - Add `_emit_fallback_event(next_chat_span, prev_model, next_model, exc)`.
  - Track `_last_failed_model` across iterations of the
    `_models` loop. On the SECOND+ iteration, emit the event
    before opening the next chat span.
- `src/ajolopy/workflow/decorator.py` + `runtime.py`:
  - Add `coordinator_fallback: list[str] | None = None` kwarg.
  - Resolve chain at decoration time via `resolve_provider` +
    `get_provider_class` (mirror the agent pattern).
  - In the coordinator turn loop, catch `LLMProviderError` and
    advance to the next coordinator model. Emit the event on the
    next chat span.
- `src/ajolopy/observability/conventions.py`: 6 new constants +
  event name.
- Tests: `tests/agent/test_fallback_observability.py`,
  `tests/workflow/test_coordinator_fallback.py`,
  `tests/agent/test_fallback_cross_provider.py`.

## Implementation notes

(Empty — populated by the implementation PR.)
