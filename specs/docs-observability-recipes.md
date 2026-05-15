# AJ-51 — Observability recipes (Langfuse, Sentry, Grafana, Honeycomb, Datadog)

> Tracked in [`board.json`](../board.json) as `AJ-51`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §10 (Observabilidad) and the
> already-shipped OTel surface in AJ-28 / AJ-30. If this file conflicts with
> the Brief, the Brief wins.

## What

Ship five **observability recipe pages** under `docs/recipes/observability/`,
one per backend (Langfuse, Sentry, Grafana stack, Honeycomb, Datadog), plus an
index page that explains the shared model ("pick an exporter, set two env
vars, you are done") and helps the reader pick.

The pages cover **how to plug each backend into the OTel pipeline that AJ-28
already ships** — no new framework hooks, no backend-specific framework code.
Every recipe is a swap of one exporter (or an env-var change against the same
OTLP exporter).

The reader's job to be done: "I just shipped my first Ajolopy agent. I picked
[backend X]. Get me to a live trace + cost dashboard in under 10 minutes."

## Why

This is one of the Brief v4.0 **non-negotiables for v0.1**: "Observabilidad:
OpenTelemetry pluggable + 5 recetas documentadas." The wedge user (AI
Engineer at a Series-A startup) does not want to read about distributed
tracing theory — they want a copy-pasteable block of env vars and a
screenshot of what the dashboard should look like.

The five backends are deliberately chosen to cover the realistic options the
wedge user will already have access to:

| Backend          | Why it is in the list                                                                 |
| ---------------- | ------------------------------------------------------------------------------------- |
| Langfuse         | AI-native — surfaces `gen_ai.*` and `gen_ai.cost_usd` out of the box.                 |
| Sentry           | Already paying for it on the JS side; their AI Monitoring product consumes OTLP.      |
| Grafana stack    | Self-hosted / on-prem / "we already have Grafana." Tempo + Loki + Prometheus + UI.    |
| Honeycomb        | High-cardinality traces, BubbleUp on outliers. Strong for debugging tail-latency.     |
| Datadog          | Enterprise default; corp pays the bill; one pane of glass with infra + APM + logs.    |

The five-recipe set keeps the framework backend-neutral: no recipe is special,
every backend is "swap an env var (or one exporter import) on top of the same
OTel pipeline."

## Design rule

This is a docs item, but it still follows the **magical default + escape
hatch** spine:

| Magical default                                                                                         | Escape hatch                                                                                                                  |
| ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Install `ajolopy[otel]`, set two env vars (`OTEL_EXPORTER_OTLP_ENDPOINT` + auth header), get spans.     | Build your own `TracerProvider`, install it before `AjolopyFactory.create()` — AJ-28 detects a real provider and skips setup. |
| Use the embedded LiteLLM pricing snapshot (AJ-30) for `gen_ai.cost_usd`.                                | Override per-model pricing via `AjolopyFactory.create(..., pricing_overrides=...)`.                                           |
| Privacy default: do not export prompt / completion text.                                                | Opt in with `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` per the official OTel GenAI env var.                    |

Each recipe page mirrors this: the body is the magical default; the
"Gotchas" + "See also" sections point at the escape hatch.

## Public surface

### Files added

```
docs/recipes/
  observability/
    index.md           # overview + decision matrix
    langfuse.md
    sentry.md
    grafana.md         # the Grafana stack: Tempo + Loki + Prometheus + Grafana
    honeycomb.md
    datadog.md
```

### Shared page template

Every recipe page follows the same six-section structure. Tight pages
(~80–150 lines each), no marketing prose.

```markdown
# <Backend>

## What you get

One paragraph: traces, cost-per-call, errors, dashboards. Tie it back to
the GenAI conventions (`gen_ai.*`, `ajolopy.*`) that AJ-28/AJ-30 emit.

## Prerequisites

Bullet list: account / project / API key / endpoint.

## Install

```bash
uv pip install "ajolopy[otel]"
```

Backend-specific extras (when applicable, e.g. Sentry's SDK).

## Wire it in

`.env` block + minimum-viable code snippet. Honor the AJ-28 surface
(`setup_tracing_from_env`, env-only OTLP, or a real `TracerProvider` set
before `AjolopyFactory.create()`).

## What you should see

2–3 bullets describing the data landing in the backend (traces,
cost-by-agent, error rate, latency by model). No screenshot files in
v0.1 — prose descriptions only.

## Gotchas

3–5 bullets: cardinality limits, sampling defaults, cost gotchas,
redaction, content-capture opt-in.

## See also

Cross-link to `@Agent`, the recipes index, and the official backend
docs.
```

### Cross-cuts

#### `mkdocs.yml` update

Add a `Recipes:` top-level section between `Reference:` and `Next steps:`.
Sub-nav for the observability set:

```yaml
nav:
  - Home: index.md
  - Quickstart: quickstart.md
  - Install: install.md
  - Tutorial:
      - ...
  - Reference:
      - ...
  - Recipes:
      - Observability:
          - Overview: recipes/observability/index.md
          - Langfuse: recipes/observability/langfuse.md
          - Sentry: recipes/observability/sentry.md
          - Grafana stack: recipes/observability/grafana.md
          - Honeycomb: recipes/observability/honeycomb.md
          - Datadog: recipes/observability/datadog.md
  - Next steps: next-steps.md
```

#### `docs/index.md` update

Add a `Recipes` card to the landing-page grid (after the Tutorial / Install
cards), linking to `recipes/observability/index.md`.

#### `docs/next-steps.md` update

Replace the "Observability recipes" "Coming soon" bullet under "Put it in
production" with concrete links into the five new pages.

## Acceptance criteria

- [ ] Six new pages exist under `docs/recipes/observability/`:
      `index.md`, `langfuse.md`, `sentry.md`, `grafana.md`, `honeycomb.md`,
      `datadog.md`.
- [ ] Each recipe page follows the six-section template (What you get,
      Prerequisites, Install, Wire it in, What you should see, Gotchas,
      See also).
- [ ] `index.md` includes a "which one should I pick?" decision matrix
      across the five backends.
- [ ] Every code snippet uses real symbols from `src/ajolopy/observability/`
      (or `ajolopy.AjolopyFactory`) — no fictional hooks.
- [ ] Every recipe declares the right install line (`ajolopy[otel]` plus
      backend-specific extra when applicable).
- [ ] `mkdocs.yml` adds a top-level `Recipes:` section between `Reference:`
      and `Next steps:`.
- [ ] `docs/index.md` adds a `Recipes` card to the landing-page grid.
- [ ] `docs/next-steps.md` replaces the "Coming soon" pointer with the new
      recipe links.
- [ ] `uv run --group docs mkdocs build --strict` succeeds (no broken
      cross-links).

## Out of scope

- **No recipe lock-in.** Every backend is a swap of an exporter + env var.
  The framework ships zero backend-specific code in `src/`.
- **No screenshot files** in v0.1. Prose descriptions of "what you should
  see" are enough; image management lands later if/when we ship a release
  blog post.
- **No new framework hooks.** Anything a backend needs that AJ-28 did not
  ship gets a Gotchas bullet linking to a board item, never an invented
  API.
- **Dashboards-as-code.** Prebuilt JSON dashboards per backend are post-v0.1
  (Brief §10 Roadmap, "Dashboards prebuilt").
- **OTel logs / metrics recipes.** This item documents traces only — that
  is what AJ-28 ships. Logs / metrics recipes ride with AJ-31 (custom
  metrics API).

## Implementation pointers

- Source content for the "What you get" sections from Brief v4.0 §10 and
  AJ-28 / AJ-30 specs.
- Match the voice of `docs/quickstart.md` and `docs/reference/agent.md`:
  imperative, pragmatic, no marketing fluff.
- Material admonitions (`!!! note`, `!!! tip`, `!!! warning`) for
  side-notes — keep them out of the main flow.
- Fence code blocks with explicit language (` ```python `, ` ```bash `,
  ` ```yaml `, ` ```env `).
- Cross-link every recipe back to `docs/reference/agent.md` and the
  recipes index.

## Implementation notes

(Empty — populated by the implementation PR.)
