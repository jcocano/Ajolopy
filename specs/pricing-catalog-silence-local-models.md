# AJ-70 — Silence pricing-catalog warning for local/custom models

> Tracked in [`board.json`](../board.json) as `AJ-70`. Status, owner, branch and
> dependencies live there — do not duplicate them in this file.
>
> Builds on top of AJ-30 (`specs/pricing-catalog.md`). The pricing catalog
> already emits a one-time WARNING per unknown model name; this item adjusts
> that behaviour so local/custom models do not contribute log noise.

## Goal

The pricing catalog (AJ-30, `src/ajolopy/observability/pricing.py`) logs

```
WARNING ajolopy.observability.pricing : Unknown model 'ollama:qwen3-coder-30b'
        — gen_ai.cost_usd omitted from spans. Register a pricing_overrides
        entry to silence this warning.
```

once per process for every model that is missing from the embedded LiteLLM
snapshot. For **cloud** models that is the right default: the user is paying
per token, the omitted `gen_ai.cost_usd` attribute is a footgun, and the
warning is how the framework tells them. For **local / self-hosted** models
(`ollama:*`, custom on-prem inference, vLLM behind a private prefix) the
warning is pure noise — there is no cost to track, and the user already knows
the model is local.

Ship a clean way to silence the warning for local / custom models **without**
weakening the default behaviour for unknown cloud models.

## Why

- Surfaced while running the AJ-66 / AJ-67 / AJ-50 examples against a local
  LM Studio / Ollama server. The warning fired on every example invocation,
  drowning out the actually-useful "your Ollama server is on the wrong port"
  noise that the AJ-66 / AJ-68 work cares about.
- Local-first onboarding is the AJ-66 wedge ("try the framework without an
  API key"). A loud cost-tracking WARNING the first time someone hits
  `ajolopy dev` against Ollama is a credibility leak — there is no cost, the
  WARN suggests the framework does not understand the user's setup.
- Cheaper than extending the pricing catalog with `ollama:*` entries (which
  would all be `0.0` anyway and confuse cost dashboards). The fix is
  observability hygiene, not catalog data.

## Design — Option D: silent-prefix list **plus** explicit override

Four options were considered (full rationale below). v0.1 ships **Option D**
(combine A + C): a small hard-coded list of "obviously local" prefixes that
silence the warning by default, **plus** an explicit `silence_models` kwarg
on `Catalog.__init__` (and a paired `pricing_silence=` on
`AjolopyFactory.create(...)`) for the power-user / custom-prefix case.

### Magical default + escape hatch

| Magical default | Escape hatch |
|---|---|
| Models whose prefix appears in `_DEFAULT_SILENT_PREFIXES` (currently just `ollama`) skip the WARNING and silently return `None` from `Catalog.get`. The chat span still omits `gen_ai.cost_usd*` — the *only* change is the log line. | `Catalog(prices, silence_models={"my-custom-model", "vllm"})` accepts a set of exact model strings **and** prefix tokens (matched against the segment before the first `:` or `/`). `AjolopyFactory.create(pricing_silence={...})` plumbs the same set through to the active catalog. |
| Existing cloud-model behaviour is unchanged: an unknown `claude-foo-99` still fires its one-time WARNING with the same message + the `pricing_overrides` hint. | `pricing_silence` and `pricing_overrides` are independent: a model can appear in both (overrides win for the math, silence wins for the warning). The two kwargs do not interact. |
| Repeat unknowns still dedupe per-model — first lookup decides, subsequent lookups stay quiet. | Subclassing `Catalog` and overriding `_should_warn(model)` is the documented seam for callers that want a richer policy (e.g. silence everything routed through a specific HTTP base URL). |

### Option comparison (why Option D)

- **Option A — silence prefixes by default.** Zero user action. Cons: opinionated
  about what "local" means; users on `vllm:` or `lmstudio:` still see noise.
- **Option B — env-var-driven silence (`AJOLOPY_PRICING_CATALOG_SILENCE=...`).**
  Explicit, runtime-tweakable. Cons: another env var to discover; clashes with
  the project's "config is code, env is for secrets / endpoints" pattern; harder
  to test (env-var mutation is global state).
- **Option C — `silence_models` kwarg only.** Matches existing
  `pricing_overrides=` UX. Cons: every local-Ollama user still has to write code
  to silence the warning — defeats the wedge of "zero ceremony for local".
- **Option D — A + C combined.** Picked. Covers the wedge case (Ollama users
  do nothing) **and** the long tail (a `vllm:` user passes
  `pricing_silence={"vllm"}` once). The silent-prefix list is **conservative**
  (one entry today, `ollama`; new prefixes are added only when the
  corresponding `_PrefixDefaults` entry has `api_key_env=None`). The escape
  hatch handles everything else.

### Silent-prefix list — what counts as "obviously local"

The list lives **in `pricing.py`** as a module-level constant
`_DEFAULT_SILENT_PREFIXES: frozenset[str] = frozenset({"ollama"})`. The rule
for extending it is documented in the module docstring:

> A prefix qualifies for the silent list when the universal-OpenAI provider
> declares its `api_key_env` as `None` AND the upstream service is intended
> to run on the operator's own infrastructure (local or self-hosted). New
> entries land behind their own PR + spec note — adding a prefix is a
> user-visible behaviour change.

Today the only matching prefix is `ollama` (cf.
`src/ajolopy/providers/universal_openai/provider.py:75-80`). The constant is
**not** imported from `universal_openai` to keep the observability module
free of provider-package dependencies; the rule is enforced by review.

### Precedence

The three silencing sources combine as a single boolean check at the
beginning of `Catalog._warn_unknown(model)`:

```
silence(model) = (
    model_prefix(model) in _DEFAULT_SILENT_PREFIXES
    OR model in self._silence_models
    OR model_prefix(model) in self._silence_models
)
```

If any of the three branches matches, the WARNING is skipped and the model is
still recorded in `_warned_unknown` so the dedup invariant ("at most one log
line per model per process") stays true even if the silence policy changes
mid-process (e.g. someone constructs a second catalog without silence).

### Backwards compatibility

- The default `Catalog()` constructor signature gains one **keyword-only**
  argument with a default of `None`. Existing positional calls
  (`Catalog({"foo": ModelPrice(...)})`) keep working unchanged.
- The default warning fires for the **exact same set of models** as before,
  minus the `ollama:*` prefix. No other change to the warning message,
  log-level, or omit-attr behaviour.
- `pricing_overrides=` continues to work the same way. A user who registered
  an override for `ollama:llama3.3` still wins on the cost math (the override
  is found by `Catalog.get` and no warning path is reached at all).

## Acceptance criteria

Every item ships behind at least one passing test.

### Catalog API

- [x] `_DEFAULT_SILENT_PREFIXES: frozenset[str]` module-level constant in
      `src/ajolopy/observability/pricing.py`, initially `{"ollama"}`. Documented
      in the module docstring with the extension rule.
- [x] `Catalog.__init__` accepts a keyword-only
      `silence_models: Iterable[str] | None = None` argument. The constructor
      copies it into a frozen set so caller mutations cannot retroactively
      affect the catalog's silence policy.
- [x] `Catalog.with_overrides` preserves the receiver's `silence_models` on
      the returned new catalog (no silent reset).
- [x] `Catalog.with_silence(*models)` returns a new catalog with the
      additional models added to the silence set (mirrors `with_overrides`
      for the silence dimension). The receiver is unchanged.
- [x] `Catalog._warn_unknown` short-circuits — without logging — when:
      (a) the model's prefix segment is in `_DEFAULT_SILENT_PREFIXES`, or
      (b) the model itself is in `self._silence_models`, or
      (c) the model's prefix segment is in `self._silence_models`.
      In all three cases the model is still added to `_warned_unknown` so
      the dedup invariant survives a later silence-policy change.

### Default cloud-model behaviour is preserved

- [x] An unknown cloud model (`claude-foo-99`, `gpt-99`) **still** logs a
      single WARNING through `ajolopy.observability.pricing` with the
      existing message format including the `pricing_overrides` hint.
- [x] The dedup per model still holds: a second `Catalog.get("claude-foo-99")`
      after the first one does not re-log.

### Silent-prefix list silences `ollama:*`

- [x] `Catalog({}).get("ollama:llama3.3")` returns `None` and emits **zero**
      log records on the `ajolopy.observability.pricing` logger.
- [x] `Catalog({}).get("ollama:llama3.3")` followed by
      `Catalog({}).get("ollama:qwen3")` still emits zero log records (silence
      applies to every model under the prefix).
- [x] The chat-span emitter behaviour is unchanged for ollama: no cost attrs
      land on the span, `compute_cost_usd` still returns `None`. Only the
      log line goes away.

### `silence_models` kwarg

- [x] `Catalog({}, silence_models={"my-custom-model"})` silences the warning
      for `"my-custom-model"` but **not** for `"my-other-model"`.
- [x] `Catalog({}, silence_models={"vllm"})` silences both `"vllm:foo"` and
      `"vllm:bar"` (prefix-token match).
- [x] `Catalog({}, silence_models=[...])` accepts any `Iterable[str]`
      (list, set, generator, tuple).

### Factory plumbing

- [x] `AjolopyFactory.create(..., pricing_silence: Iterable[str] | None = None)`
      forwards the silence set into the active catalog. When both
      `pricing_overrides` and `pricing_silence` are passed, the resulting
      active catalog has overrides merged AND silence applied.
- [x] When `pricing_silence` alone is passed (no overrides), the factory
      still installs a fresh active catalog so the silence applies to every
      future cost emission.
- [x] When neither is passed, the active catalog reverts to the lazy
      default — no behaviour change from before AJ-70.

### Lint / type / format / test gates

- [x] `uv run ruff check` clean.
- [x] `uv run ruff format --check` clean.
- [x] `uv run pyright` clean in strict mode.
- [x] `uv run pytest` green — the full suite, not just the new tests.
- [x] `uv run mkdocs build --strict` clean (docs note for the silence options
      lands on `docs/recipes/observability/index.md`).

## Out of scope

- **Auto-detect "this URL is local" via the base URL.** Inspecting the
  resolved client URL ties the pricing layer to provider internals; not
  v0.1 material.
- **Per-tenant / per-user silencing.** Process-wide policy is enough for
  v0.1; multi-tenant pricing is a v0.2+ concern (see AJ-30 § Out of scope).
- **Env-var-based silencing.** Option B was rejected for the reasons
  documented above. Reopen the discussion in v0.2 if user feedback shows
  the kwarg is too clumsy for deploy-time silencing.
- **Adding pricing data for local models.** AJ-70 is strictly about the
  warning — not about extending the catalog. Local models that route
  through a real billing surface (e.g. an Ollama-hosted-on-Modal deploy
  with a price-per-token contract) still use `pricing_overrides`.

## Implementation pointers

- Edit: `src/ajolopy/observability/pricing.py`
  - Add `_DEFAULT_SILENT_PREFIXES: frozenset[str] = frozenset({"ollama"})`.
  - Add `_prefix_segment(model: str) -> str | None` helper that returns the
    segment before the first `:` or `/` (or `None` for a bare name).
  - Extend `Catalog.__init__` with `*, silence_models: Iterable[str] | None = None`.
  - Add `Catalog.with_silence(*models: str) -> Catalog`.
  - Make `Catalog._warn_unknown` consult the three-source silence rule.
  - Update `with_overrides` to forward `_silence_models` to the new catalog.
- Edit: `src/ajolopy/factory/factory.py`
  - `AjolopyFactory.create(..., pricing_silence: Iterable[str] | None = None)`.
  - When either kwarg is non-empty, build the catalog as
    `Catalog.from_snapshot().with_overrides(overrides or {}).with_silence(*silence)`.
- Edit: `docs/recipes/observability/index.md` — add a short
  "Silencing the unknown-model warning" tip explaining both layers (default
  silence for `ollama:*`, kwarg for custom prefixes).
- New: tests in `tests/observability/test_pricing_unknown_model.py` (or a
  fresh `test_pricing_silence.py`) for the four sub-categories above.
- New: factory plumbing test in
  `tests/observability/test_pricing_overrides.py` (or a fresh
  `test_pricing_silence_factory.py`) that exercises
  `AjolopyFactory.create(pricing_silence=...)`.

## Implementation notes

- The `silence_models` value is normalised to a `frozenset[str]` inside
  `Catalog.__init__` for the same reason `_prices` is copied — so caller
  mutations cannot retroactively shift the catalog's policy.
- The `_warned_unknown` set still records every unknown model regardless of
  whether the warning fired. This keeps the dedup invariant true if the
  silence policy changes mid-process: a model that was silent on the first
  lookup remains silent on the second, even if the silence list shrinks in
  between.
- The silent-prefix list is intentionally **not** sourced from
  `_PREFIX_DEFAULTS` (the universal-OpenAI provider's table). Coupling the
  observability layer to the provider package would import a much heavier
  dependency graph at logger init time. The two-line constant in `pricing.py`
  plus the documented extension rule is the right trade-off for a v0.1
  framework.
