# AJ-30 — Internal pricing catalog + automatic `gen_ai.cost_usd` per span

> Tracked in [`board.json`](../board.json) as `AJ-30`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §6 (dolor #2 "bill shock de LLM")
> and §10 (Observabilidad). Bridges directly to AJ-28's GenAI-conv span tree.
> If this file conflicts with the Brief, the Brief wins.

## What

Ship an internal **pricing catalog** plus a thin **cost-math layer** that turns
the `gen_ai.usage.*_tokens` already on every `chat` span (AJ-28) into
**`gen_ai.cost_usd` attributes**, automatically, with zero user setup. The
result: every Langfuse / Honeycomb / Datadog dashboard built on top of an
Ajolopy app can answer "how much did this user cost us this month" with one
query, instead of joining usage × pricing in SQL or relying on Langfuse Pro.

The catalog itself is an embedded snapshot of LiteLLM's
[`model_prices_and_context_window.json`](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
(MIT-licensed, community-maintained). A monthly CI workflow re-fetches the
upstream JSON and opens a PR when prices drift. Users with custom / on-prem /
brand-new models can register `pricing_overrides={...}` at framework level so
they never wait on a release.

Pricing is **tiered**: input, output, cache-creation input (Anthropic prompt
caching writes), and cache-read input (cache hits). Without the cache tiers,
an agent with prompt caching on would have its cost undercounted by up to
10× when most of its input lands on cache reads (~$0.50/MTok vs $5.00/MTok for
Opus 4.7).

The instrumentation auto-emits on the `chat` span (and aggregates the total on
the `agent.invoke` root). The math is also exposed as a public helper —
`compute_cost_usd(model, ...) -> float | None` — so future primitives (`@Embed`,
`@Memory`, vectorstore spans) that open their own spans can pick up cost
emission without re-implementing the catalog.

## Why

The wedge user (AI Engineer at a Series A) has dolor #2 in the Brief at a
literal 2am page: "who consumed $4k this month?" Their options today:

1. **Build it themselves**: query the spans, join against a hand-maintained
   pricing table, hope nothing changed mid-month. Days of work + ongoing
   maintenance.
2. **Pay Langfuse Pro**: $59/team/month, locked in.
3. **Eat the bill**: most popular option in practice, which is exactly the
   problem.

Ajolopy ships option 4: every span already has `gen_ai.cost_usd` baked in, so
the answer is `SUM(gen_ai.cost_usd) GROUP BY user_id` against whatever
backend the user's traces flow to. This is the single feature with the
loudest user-visible payoff per line of code in the framework's v0.1.

AJ-30 unblocks AJ-31 (custom metrics API), AJ-51 (observability recipes
showing real cost dashboards), and AJ-54 (the docs bot dogfood app — the user
explicitly cares about being able to point at its monthly LLM cost).

## Design rule

| Magical default | Escape hatch |
|---|---|
| `compute_cost_usd` and the `chat`-span auto-emit work out of the box for every model in the LiteLLM snapshot — no user code needed. | Users register `pricing_overrides={"my-model": {"input_cost_per_token": 0.000001, "output_cost_per_token": 0.000003, ...}}` at framework level (via `AjolopyFactory.create(..., pricing_overrides=...)` or an env-var override file) for custom / on-prem / brand-new models. The override **wins** over the embedded snapshot. |
| Embedded JSON is the source of truth for prices: zero network in the hot path; updates land via versioned PRs. | The same `pricing_overrides=` plus a future `--catalog=<path>` opt-in lets users point at a fresher local JSON without waiting on a release. |
| Unknown models → `gen_ai.cost_usd` attr is **omitted**, a one-time warning is logged per model name, and the span is otherwise normal. | Same `pricing_overrides=` adds entries for unknown models; the warning stops once the model is registered. |

## Decisions locked before implementation

- **Catalog source**: embedded snapshot of LiteLLM's
  `model_prices_and_context_window.json` (MIT). Snapshot file:
  `src/ajolopy/observability/pricing.json`. LICENSE attribution in `NOTICE`
  at the repo root (created if absent). LiteLLM upstream is community-driven,
  versioned in their `main` branch — pinning a snapshot avoids surprise
  breakage when they reshape the JSON.
- **Pricing tiers** (v0.1): `input`, `output`, `cache_creation_input`
  (Anthropic prompt-cache writes), `cache_read_input` (cache reads — Anthropic
  / OpenAI / Gemini all report this). Batch / image / audio rates: post-v0.1.
- **Unknown model**: omit the `gen_ai.cost_usd*` attrs, log a one-time
  warning per `model` string. Never emit `cost_usd=0.0` (silently misleading).
- **Escape hatch — `pricing_overrides`**: a `dict[str, ModelPrice]` accepted at
  `AjolopyFactory.create(...)` and merged on top of the embedded snapshot.
  Documented as the supported way to (a) cover models the catalog does not
  ship yet, (b) override prices for custom contracts (e.g. negotiated rates).
- **Emission shape**: per-call attrs on the `chat` span, plus a single
  `ajolopy.cost_usd.total` on the `agent.invoke` root that is the sum of all
  child chat-span costs (so a backend dashboard can graph per-agent spend
  without span aggregation queries). Each `chat` span carries five attrs:
  - `gen_ai.cost_usd` (total — input + output + cache_creation + cache_read)
  - `gen_ai.cost_usd.input`
  - `gen_ai.cost_usd.output`
  - `gen_ai.cost_usd.cache_creation`
  - `gen_ai.cost_usd.cache_read`
- **Wire-type extension is in scope**: `ChunkUsage` and `Response` gain two
  new int fields (`cache_creation_input_tokens`, `cache_read_input_tokens`,
  both default 0). Without them, cache-tier pricing is impossible. Providers
  populate the new fields from their SDKs.
- **Embeddings — math API, no auto-emit**: `compute_cost_usd(...)` is part of
  the public surface and accepts `input_tokens` only (no output). Embeddings
  do not get a span in v0.1 (`provider.embed()` is called without an
  open-span wrap; AJ-28's rule "providers are pure adapters" still stands).
  Future primitives that open `embeddings {model}` spans pick up the same
  math layer for free. **Scope note**: AJ-30 does NOT instrument
  `provider.embed()`. That lands when an `@Embed` / `@Memory` / vectorstore
  primitive arrives.
- **Currency**: USD only (the attr name `gen_ai.cost_usd` bakes it in).
  Multi-currency is a v0.2+ concern with its own attribute namespace.
- **Refresh policy**: the snapshot is static. A CI script `tools/sync_pricing.py`
  fetches the upstream JSON, diffs it against the embedded copy, prints a
  human-readable diff, and is invoked by a scheduled GitHub Action
  (`.github/workflows/sync-pricing.yml`) on a monthly cron. The Action opens
  a PR `chore(pricing): sync LiteLLM snapshot YYYY-MM-DD` when there are
  changes. Manual invocation: `uv run python tools/sync_pricing.py`.

## Module layout

```
src/ajolopy/observability/
  pricing.py              # ModelPrice dataclass + Catalog + compute_cost_usd
  pricing.json            # embedded LiteLLM snapshot (data, not code)
  pricing_emit.py         # private — applies cost attrs to spans (called by AgentRuntime)
  tracing.py              # AJ-28 — unchanged
  conventions.py          # AJ-28 — extended with gen_ai.cost_usd.* keys
  logging.py              # AJ-29 — unchanged

src/ajolopy/providers/
  types.py                # ChunkUsage + Response gain cache_creation_input_tokens, cache_read_input_tokens
  anthropic/provider.py   # populate cache tier fields from SDK
  openai/provider.py      # populate cache tier fields from SDK (prompt_tokens_details.cached_tokens)
  gemini/provider.py      # populate from usage_metadata.cached_content_token_count
  universal_openai/provider.py  # mirror openai

src/ajolopy/agent/runtime.py
  # chat-span helper reads usage tiers + emits cost attrs; root span gets cost roll-up
  # accepts pricing_overrides via the constructor (forwarded by @Agent)

src/ajolopy/factory/factory.py
  # AjolopyFactory.create(..., pricing_overrides=...) plumbs the dict into the runtime

NOTICE                    # MIT attribution for LiteLLM snapshot (new file)

tools/sync_pricing.py     # diff + report; opens nothing — the workflow handles PR creation
.github/workflows/sync-pricing.yml  # monthly cron + diff + open-PR

tests/observability/
  test_pricing_catalog.py       # loading, override merging, lookup, unknown handling
  test_pricing_math.py          # compute_cost_usd per tier, totals, edge cases (zero tokens, float precision)
  test_pricing_emit_chat_span.py# chat span gets all 5 attrs from FakeProvider tokens
  test_pricing_emit_root_total.py# agent.invoke gets ajolopy.cost_usd.total
  test_pricing_unknown_model.py # warning once, attrs omitted
  test_pricing_overrides.py     # pricing_overrides wins over snapshot
  test_sync_pricing_script.py   # diff logic on canned fixtures
```

## Acceptance criteria

Every item ships behind at least one passing test.

### Catalog data + loader

- [x] `src/ajolopy/observability/pricing.json` is the **full LiteLLM
      `model_prices_and_context_window.json`** snapshot, copied verbatim from
      upstream's `main` at a pinned commit. No curation, no field renaming —
      whatever LiteLLM ships, we ship, so the sync script's field-by-field
      diff stays trivial. The pinned upstream commit SHA is recorded in the
      file's leading `metadata` block (LiteLLM already keeps this) or in
      `tools/sync_pricing.py` as a constant.
- [x] `NOTICE` file at repo root attributes LiteLLM with the MIT licence text
      and a link to the upstream JSON, plus the snapshot date.
- [x] `Catalog.load_default()` returns a `Catalog` with every model in the
      snapshot loaded. Asserted by lookups for: an Anthropic model, an OpenAI
      model, a Gemini model, an embeddings model, and an
      OpenAI-compatible-aliased model (e.g. `groq/llama-3.3-70b-versatile`).
- [x] Loading the catalog at import time costs < 50 ms despite the full
      snapshot being ~500 KB (asserted with a `perf_counter` smoke test). If
      the simple `json.load` pass exceeds the budget, the loader falls back
      to a lazy lookup that parses on demand.

### Model-name normalisation (universal-OpenAI lookup)

- [x] `Catalog.get(model)` normalises the lookup key by replacing the
      universal provider's `:` separator with LiteLLM's `/` separator before
      the table lookup. So an Ajolopy model string
      `"groq:llama-3.3-70b-versatile"` resolves against the LiteLLM entry
      `"groq/llama-3.3-70b-versatile"` transparently.
- [x] When the normalised key is still not present, the same lookup is
      attempted with the route prefix stripped (e.g. `"groq:llama-3.3-70b"`
      → `"groq/llama-3.3-70b"` → `"llama-3.3-70b"`). This matches users who
      route a bare model through their own custom prefix.
- [x] Native providers (Anthropic, OpenAI, Gemini) pass the model unchanged
      to `Catalog.get`; the normalisation is a no-op for them.
- [x] The normalisation rule is documented in the module docstring of
      `pricing.py` so future provider authors know to either match the
      LiteLLM key or register an alias.

### `compute_cost_usd` math

- [x] Signature: `compute_cost_usd(model: str, *, input_tokens: int = 0, output_tokens: int = 0, cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0, catalog: Catalog | None = None) -> float | None`.
- [x] Returns `None` for an unknown model (precondition for the omit-attr
      branch in the emitter).
- [x] Returns `0.0` only when the model is known AND every token count is 0.
- [x] Math: `cost = sum_over_tiers(tokens × price_per_token)`. Asserted with
      two real-world numbers (Opus 4.7 input 1000 tokens × $5/MTok = $0.005;
      Opus 4.7 cache read 1000 tokens at $0.50/MTok = $0.0005).
- [x] When a tier price is missing in the snapshot (e.g. OpenAI models without
      `cache_creation_input_token_cost`), the missing tier contributes 0 to
      the total (does NOT make the whole call return None).
- [x] Float precision: 1 billion input tokens at $3/MTok returns $3000.0 with
      sub-cent precision intact (regression guard on float arithmetic).

### Override merging

- [x] `Catalog.with_overrides({"acme-model": ModelPrice(input_cost_per_token=1e-6, output_cost_per_token=3e-6)})` returns a new catalog where
      `compute_cost_usd("acme-model", input_tokens=1000)` returns 0.001.
- [x] Overriding a model already in the snapshot replaces its prices entirely
      (no per-tier merge — explicit, predictable).
- [x] `pricing_overrides` accepted at `AjolopyFactory.create(...)` flows
      through to the runtime's catalog instance.

### Wire-type extension (touches AJ-28 surface)

- [x] `ChunkUsage` gains `cache_creation_input_tokens: int = 0` and
      `cache_read_input_tokens: int = 0` (back-compat: default 0 means the
      existing `Chunk` instantiations in tests keep compiling).
- [x] `Response` gains the same two fields. Existing constructions stay
      compatible.
- [x] AnthropicProvider populates both from `message.usage.cache_creation_input_tokens` and `message.usage.cache_read_input_tokens` on `complete()`; same in the streaming `message_start` / `message_delta` events.
- [x] OpenAIProvider populates `cache_read_input_tokens` from
      `usage.prompt_tokens_details.cached_tokens` on `complete()` and on the
      streaming terminal usage chunk. `cache_creation_input_tokens` stays 0
      (OpenAI does not split that out — cache writes are billed at the input
      rate).
- [x] GeminiProvider populates `cache_read_input_tokens` from
      `usage_metadata.cached_content_token_count`. `cache_creation_input_tokens` stays 0 (Gemini cache creation is billed separately as part of input).
- [x] UniversalOpenAIProvider mirrors OpenAI; missing fields stay 0
      gracefully when an upstream server does not report cache details.

### `chat`-span emission

- [x] When the chat-span helper closes a non-streaming call to a known model,
      it sets `gen_ai.cost_usd`, `gen_ai.cost_usd.input`,
      `gen_ai.cost_usd.output`, `gen_ai.cost_usd.cache_creation`,
      `gen_ai.cost_usd.cache_read`. Asserted with the OTel SDK
      `InMemorySpanExporter`.
- [x] The same five attrs land on a streaming chat span (uses
      `Chunk.usage` populated by the terminal chunk).
- [x] When the model is unknown and no override applies, none of the five
      attrs are present on the chat span.
- [x] When the model is unknown, exactly one warning is logged per `model`
      string per process — repeat calls do not flood the log.

### `agent.invoke` roll-up

- [x] A run with a single chat call sets `ajolopy.cost_usd.total` on the
      `agent.invoke` root equal to the chat span's `gen_ai.cost_usd`.
- [x] A run with N chat calls (tool loop) sets `ajolopy.cost_usd.total`
      equal to the sum of the children's `gen_ai.cost_usd` values.
- [x] When at least one child chat span has no cost (unknown model), the
      root's `ajolopy.cost_usd.total` is the sum of the children that DO
      have cost. The root attr is still emitted unless **every** child is
      uncovered, in which case it is omitted.
- [x] Fallback runs (sibling chat spans under one invoke from AJ-28) roll
      up the same way.

### `compute_cost_usd` is the public embeddings entry point

- [x] `from ajolopy.observability import compute_cost_usd` is part of the
      package public surface.
- [x] Calling `compute_cost_usd("text-embedding-3-small", input_tokens=1000)`
      against the default catalog returns a non-`None` float (proof that
      embedding entries are populated and reachable via the same helper).
- [x] No spans are emitted around `provider.embed()` in v0.1. This is
      verified by a regression test: an embed call against a configured
      tracer yields zero new spans.

### Sync script + workflow

- [x] `uv run python tools/sync_pricing.py --check` returns exit code 0 when
      the embedded snapshot matches the upstream `main` JSON; non-zero with
      a human-readable diff otherwise. (The `--check` flag is what the
      monthly workflow runs to decide whether to open a PR.)
- [x] The CI workflow `.github/workflows/sync-pricing.yml` runs on a
      monthly cron and opens a PR with the new snapshot when a diff exists.
      No PR when the snapshot matches.
- [x] The workflow uses `actions/checkout@<pinned-sha>` and
      `peter-evans/create-pull-request@<pinned-sha>` (or equivalent) — no
      floating tags, per the project's security baseline.

### Lint / type / format / test gates

- [x] `uv run ruff check` clean.
- [x] `uv run ruff format --check` clean.
- [x] `uv run pyright` clean in strict mode.
- [x] `uv run pytest` green — the full suite, not just the new tests.

## Implementation pointers

- New: `src/ajolopy/observability/pricing.py`
  - `@dataclass(frozen=True, slots=True) class ModelPrice: input_cost_per_token: float = 0.0; output_cost_per_token: float = 0.0; cache_creation_input_token_cost: float = 0.0; cache_read_input_token_cost: float = 0.0`
  - `class Catalog`: `load_default() -> Catalog`, `with_overrides(...) -> Catalog`, `get(model) -> ModelPrice | None`.
  - `def compute_cost_usd(model, *, input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0, catalog=None) -> float | None`.
- New: `src/ajolopy/observability/pricing.json` — verbatim subset of LiteLLM upstream. Keep the upstream's key names (`input_cost_per_token` etc.) so the sync script's diff stays trivial.
- New: `src/ajolopy/observability/pricing_emit.py` — private. Functions `set_chat_cost_attrs(span, *, model, tokens, catalog)` and `set_root_cost_total(span, child_costs)`. Called from `AgentRuntime`.
- Edit: `src/ajolopy/observability/conventions.py` — add `GEN_AI_COST_USD`, `GEN_AI_COST_USD_INPUT`, `GEN_AI_COST_USD_OUTPUT`, `GEN_AI_COST_USD_CACHE_CREATION`, `GEN_AI_COST_USD_CACHE_READ`, `AJOLOPY_COST_USD_TOTAL`.
- Edit: `src/ajolopy/observability/__init__.py` — re-export `compute_cost_usd`, `Catalog`, `ModelPrice`, plus the new constants.
- Edit: `src/ajolopy/providers/types.py` — add the two new int fields.
- Edit: each provider's `complete()` + `stream()` paths to populate them.
- Edit: `src/ajolopy/agent/runtime.py`:
  - Constructor takes `catalog: Catalog | None = None`.
  - `_chat_span()` helper calls `set_chat_cost_attrs` after the call returns / stream closes.
  - `_invoke_span()` collects child costs and sets the root total at close.
- Edit: `src/ajolopy/agent/decorator.py` — accept `catalog` kwarg, pass through.
- Edit: `src/ajolopy/factory/factory.py` — `AjolopyFactory.create(..., pricing_overrides: dict | None = None)` instantiates a Catalog with overrides and passes it down via a module-scope or per-runtime hook (TBD — the simplest is a module-level `set_default_catalog(...)` called from the factory).
- New: `tools/sync_pricing.py` — fetches the upstream JSON, walks both catalogs, emits a unified diff to stdout; `--check` mode returns non-zero on drift.
- New: `.github/workflows/sync-pricing.yml` — runs `uv run python tools/sync_pricing.py --check`; on non-zero, runs the same script in `--write` mode (overwrites the snapshot) and opens a PR.
- New: `NOTICE` at repo root with the LiteLLM MIT attribution.

## Out of scope

- **Batch / image / audio token rates.** v0.2.
- **Multi-currency.** The attr name `gen_ai.cost_usd` is the OTel-community
  convention. EUR / GBP / per-customer billing currencies → v0.2+.
- **Per-customer pricing contracts.** Enterprise users with negotiated rates
  use `pricing_overrides`. Fancier per-tenant tables → v0.3.
- **Embeddings auto-emit.** Math is ready; the wrapping span lands with
  `@Embed` / `@Memory` / vectorstore primitives.
- **Cost budgets / kill-switch on overspend.** Different concern (auth /
  middleware). Out of v0.1 entirely.
- **Token prediction / pre-call cost estimation.** Different system; v0.2 if
  we ship `@Predict`.

## Implementation notes

- **Snapshot pinning.** The bundled `pricing.json` is the full LiteLLM
  `model_prices_and_context_window.json` at upstream commit
  `410ce761dc234ba0f5a874c1415f5c423e87d860`. The SHA is recorded in
  `tools/sync_pricing.py` (`LITELLM_UPSTREAM_SHA` constant) and in the
  repo-root `NOTICE`. The sync script's `--write` mode updates both.
- **Default-catalog seam.** `AgentRuntime` resolves the active catalog
  *lazily* on first chat-span emission via `get_active_catalog()`. The
  factory installs the merged catalog (default + `pricing_overrides`)
  via `set_default_catalog` at bootstrap. This decouples decorator-time
  construction from factory-time bootstrap so agents declared at import
  time still see overrides applied at `AjolopyFactory.create(...)` time.
- **Unknown-model logging.** `Catalog._warn_unknown` keeps a per-instance
  `_warned_unknown` set behind a `threading.Lock`, so each model string
  fires at most one warning per process. The warning routes through
  stdlib `logging.getLogger("ajolopy.observability.pricing")` so
  `pytest`'s `caplog` fixture captures it without requiring the framework's
  structlog pipeline to be configured first.
- **Embeddings.** `compute_cost_usd` is exposed as a public helper but
  `provider.embed()` is left un-instrumented per the spec — a regression
  test in `test_pricing_math.py` guards that an embed call yields zero
  spans. The wrapping span lands later with `@Embed` / `@Memory`.
- **Pricing emit module.** The private `pricing_emit.py` carries
  `set_chat_cost_attrs` (per-call) and `set_root_cost_total` (per-invoke
  roll-up). The runtime threads a `child_costs: list[float | None]`
  through the `run` / `stream` paths; the invoke-span helper reads it
  once the body finishes to write `ajolopy.cost_usd.total`.
