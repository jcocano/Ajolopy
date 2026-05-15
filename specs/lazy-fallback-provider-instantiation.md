# AJ-69 — Lazy-instantiate fallback providers

> Tracked in [`board.json`](../board.json) as `AJ-69`. Refactor of
> `AgentRuntime` so a fallback provider's `__init__` (and therefore its
> env-var validation) is deferred until the fallback actually fires.

## What

Today `AgentRuntime.__init__` eagerly instantiates every provider in the
primary + fallback chain so a missing env var in a fallback's
`__init__` (e.g. `ANTHROPIC_API_KEY` for a `claude-haiku-4-5` fallback)
fails the decorator even when the primary never errors.

This item refactors construction so:

- The **primary** model still resolves AND instantiates eagerly. Decoration-
  time validation is part of the framework's "fail fast" contract; we
  keep it.
- Every **fallback** model still resolves its provider *key* eagerly
  (an unknown prefix in a fallback list still raises `AgentConfigError`
  at decoration time), but the provider *instance* is only constructed
  on the first attempt to use that fallback.
- Provider instances are still cached per provider key: once a
  fallback's provider has been built once, every subsequent fallback
  entry routed to the same key reuses the cached instance — same
  contract as the current eager `provider_cache` dict, just
  lazy-populated.
- If a fallback fails to instantiate at run time (e.g. its env var is
  missing), the runtime emits a `WARNING` log, then advances to the
  next entry. If every fallback in the chain fails (either to
  instantiate OR to respond), the original primary `LLMProviderError`
  is re-raised wrapped in `AgentProviderError` whose message lists
  every fallback that was attempted and why each one failed.

## Why

While testing the AJ-50 / AJ-54 / AJ-63 / AJ-64 / AJ-65 / AJ-67
examples against a local LM Studio endpoint (primary
`ollama-openai:<model>` against `http://localhost:1234/v1`), the
examples still required `ANTHROPIC_API_KEY=test-dummy` purely to
satisfy the eager `Anthropic.__init__` for the fallback
`claude-haiku-4-5`. That's a friction point for the wedge user (AI
Engineer running an example without an Anthropic key) and not the
behavior the eager-validation contract is supposed to police: we
promised "fail fast on the primary", not "force the user to have an
env var for a code path they'll never reach".

## Public surface

Unchanged. `@Agent(fallback=...)` accepts the exact same shapes
(`str | list[str] | Callable | None`). The behavioral change is
entirely internal to `AgentRuntime`.

## Behavior contract (binding)

1. **Primary eager.** `AgentRuntime.__init__` calls
   `_instantiate_provider(primary_key)` and stores the instance in
   the cache before returning. A failing primary `__init__` still
   raises `AgentConfigError` at decoration time.
2. **Fallback key + class registration eager.** For each fallback
   entry, the provider key is resolved via `_resolve_provider_key`
   AND the bound `LLMProvider` class is looked up via
   `get_provider_class` at construction time. An unknown prefix
   (e.g. `fallback="totally-fake-model"`) or a key whose provider
   class has never been imported (e.g. `fallback="gpt-4o-mini"`
   with `ajolopy.providers.openai` never imported) still raises
   `AgentConfigError` at decoration time. This preserves the
   "fail fast on typos / unregistered providers" contract. What
   stays deferred is only the `cls()` constructor call — i.e.
   the step where `__init__` reads env vars and validates them.
3. **Fallback instance lazy.** Fallback entries are stored without an
   instance attached. The first time the runtime advances past the
   primary, it builds the missing instance (and caches it for the
   rest of the runtime's lifetime).
4. **Caching is provider-keyed.** Two fallback entries routed to the
   same provider key share one cached instance, identical to the
   pre-refactor behavior.
5. **Instantiation failure at run time.**
   - Log a `WARNING` with the provider key, the model string, and
     the underlying exception.
   - Advance to the next entry in the chain without yielding a
     chat span (we cannot make a request without a provider).
   - If every fallback fails to instantiate, the runtime falls
     through to the existing "all providers exhausted" path. The
     raised `AgentProviderError` message must mention each fallback
     that was attempted AND its instantiation error, so the user
     can diagnose which env var is missing.
6. **Callable fallback.** Untouched. The callable path bypasses the
   model chain entirely, so the lazy-vs-eager distinction does not
   apply.
7. **Observability unchanged.** `emit_fallback_events_on_span` still
   records `gen_ai.chat.fallback` transitions ONLY between models
   that actually emitted a chat span. A fallback that failed to
   instantiate does NOT produce a transition event (there's no
   chat span to attach it to); the WARNING log is the audit trail
   for that case.

## Backwards-compat notes

This is an additive behavior change for one class of users only:
those whose code relied on decoration-time validation of a
fallback's env var. After this refactor, that error surfaces at
first failure of the primary (when the fallback chain actually
fires) rather than at decoration. Users who never trigger a
fallback never see the error — which is exactly the goal.

The AJ-50 / AJ-54 / AJ-63 / AJ-64 / AJ-65 / AJ-67 example tests
currently set `ANTHROPIC_API_KEY=test-dummy` purely to satisfy the
eager check. Those `os.environ` setters can stay in place; the
refactor doesn't require removing them and removing them would be
churn outside this item's scope.

## Out of scope

- Changing **when** the runtime decides a fallback should fire
  (the retry policy lives in the `LLMProviderError` catch in
  `run` / `stream`; that's AJ-23's territory and untouched here).
- The fallback observability layer (`emit_fallback_events_on_span`)
  — untouched.
- The callable form of `fallback=` — untouched.
- A public hook to override `_instantiate_provider`. If a user
  needs that, future enhancement — flag it under
  `## Future enhancements` rather than smuggling it in here.
- `WorkflowRuntime._coordinator_models` carries the same eager
  shape (AJ-23). It has the same latent issue but a separate
  consumer surface and tests; if we ever surface the same friction
  there, file a follow-up item.

## Acceptance criteria

- [x] `AgentRuntime._models` keeps the
      `tuple[str, LLMProvider | None, str]` shape but the second
      slot is `None` for fallback entries until they fire (primary
      is never `None`).
- [x] A new helper `_ensure_provider(index) -> LLMProvider` lazily
      instantiates the provider for that index, caches it on the
      per-runtime provider cache, mutates the `_models[index]`
      tuple in place, and returns the instance.
- [x] `run` / `stream` call `_ensure_provider(index)` before invoking
      the provider for each entry in the chain. Existing fallback
      tests stay green.
- [x] Constructing `@Agent(model="gpt-4o-mini",
      fallback="claude-haiku-4-5")` does NOT call
      `Anthropic.__init__` when only the OpenAI key is exported.
      A unit test asserts that with a counting fake.
- [x] If both primary and the only fallback can't instantiate at
      fire time, the raised `AgentProviderError` mentions BOTH
      providers' failures (the message lists every entry that was
      attempted and the reason each one failed). A unit test
      asserts this.
- [x] The existing tests in `tests/agent/test_fallback.py`,
      `tests/agent/test_fallback_cross_provider.py`,
      `tests/agent/test_fallback_observability.py`, and
      `tests/agent/test_streaming.py` stay green without
      modification of their assertions on the public agent
      surface. Internal-attribute assertions on `_models[i][1]`
      may be tightened to `_ensure_provider(i)` when the test is
      specifically inspecting a fallback provider; primary
      assertions stay as `_models[0][1]`.
- [x] `pyright --strict` clean, `ruff` clean, full pytest green.

## Implementation pointers

- `src/ajolopy/agent/runtime.py` — only file with behavior change.
- `tests/agent/test_fallback.py` — new tests live near the existing
  fallback cases.
- The provider cache lives at runtime scope (one dict per
  `AgentRuntime` instance, not class-level), matching the current
  eager-cache scope.

## Future enhancements (deferred)

- A pluggable `provider_factory=` hook on `@Agent` (or on the
  framework registry) that lets users intercept the
  `_instantiate_provider` step for advanced cases like sharing a
  pre-warmed client across many agents. Not needed for v0.1.
- `WorkflowRuntime` mirror — apply the same lazy treatment to the
  coordinator's fallback chain. File as a separate item if the
  friction reappears in workflow examples.
