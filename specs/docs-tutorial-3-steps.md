# AJ-48 — Tutorial: the 3-step killer demo arc

> Status: ready · Type: docs · Priority: p0 · Milestone: v0.1
> Blocks: AJ-50 (full support-agent example end-to-end)
> Blocked by: AJ-1, AJ-2, AJ-3, AJ-4, AJ-6, AJ-7 — all `done`.

## Goal

Ship the **3-step killer demo arc** as the prose tutorial for v0.1. The arc
turns a five-minute Quickstart graduate into someone who has just written a
multi-agent, MCP-integrated, eval-guarded support system — in ~55 lines.

This is the highest-leverage docs deliverable of v0.1:

- It is what the [Brief v4.0 § 4 Killer demo](../board.json) calls "el viral
  del README".
- It unblocks [`AJ-50`](../specs/docs-examples.md) (full standalone example
  app) and contributes to [`AJ-57`](../board.json) (public launch).
- It is what every reader who finishes [`Quickstart`](../docs/quickstart.md)
  needs next — today the [`docs/next-steps.md`](../docs/next-steps.md) page
  links a `Coming soon` placeholder for it.

## The arc (locked by Brief v4.0)

| Step | Adds       | Demonstrates |
|------|------------|--------------|
| 1. Hello to prod        | ~12 lines | One agent + one tool + one stream endpoint — production-grade from day one (`fallback`, `trace`, env validation, tool calling loop, SSE). |
| 2. Evals — bloquea PRs  | +12 lines | `@Eval` + `@Metric` over the Step 1 agent. Regression detection via `ajolopy eval --ci` exits non-zero. |
| 3. Equipo — multi-agent + MCP | +30 lines | `@Workflow(coordinator=..., agents=[Triage, Billing, Technical], integrations=[Integrations])` with `@MCP` integrations and a workflow-level `@Eval`. |

## Voice and style

- Match the [`Quickstart`](../docs/quickstart.md) voice: imperative,
  pragmatic, no marketing fluff. "This is the round trip" beats "let's
  explore how Ajolopy elegantly enables...".
- Every code snippet must be **real and runnable** against the v0.1 surface
  — no pseudo-code, no `# TODO: imagine`. Snippets that drift from the
  current decorator signatures are bugs.
- Each step page ends with a `## What just happened` callout matching the
  Quickstart pattern, and a `## What's next` linking the next step (or for
  Step 3, linking AJ-50 and the per-primitive reference).
- Use Material admonitions (`!!! note`, `!!! tip`, `!!! warning`) for
  side-channel notes; do not derail the main flow.

## Drift between Brief and current API

The Brief sketches the arc; the v0.1 implementation is the source of truth
for syntax. Known reconciliations the tutorial must honour:

- `@Workflow` has no `trace=True` kwarg. Tracing is enabled globally via
  OpenTelemetry bootstrap; the workflow inherits it. Document this once and
  do not repeat the false kwarg.
- `@MCP(servers=...)` requires transport-prefixed strings
  (`"stdio:npx -y @modelcontextprotocol/server-github"` or `https://...`).
  The Brief's `["zendesk", "stripe", "linear"]` is illustrative — Step 3
  must use real transports (recommend `github` MCP since the `@MCP`
  reference already uses it).
- `@Eval(agent=..., dataset=..., threshold=..., concurrency=...)` is the
  real signature; `@Metric` is alive (AJ-5 was renamed/absorbed into
  AJ-4, not removed).

## Acceptance criteria

- [ ] `docs/tutorial/index.md` — overview page covering the arc table, the
      "55 lines vs 800" framing from the Brief, and links to Steps 1–3.
- [ ] `docs/tutorial/step-1-hello.md` — Step 1 "Hello to prod" with a
      runnable `Support` agent (`@Agent` + `@Tool` + `@Stream`), the
      `fallback=` and `trace=True` knobs, and the env-validation reveal.
- [ ] `docs/tutorial/step-2-evals.md` — Step 2 "Evals" with `@Eval`,
      two `@Metric` methods (an LLM-judge style scorer and a deterministic
      safety scorer), the JSONL dataset shape, and the
      `ajolopy eval --ci` regression detection demo.
- [ ] `docs/tutorial/step-3-team.md` — Step 3 "Equipo" with `Triage`,
      `Billing`, `Technical`, a real `@MCP` integration block,
      `@Workflow(coordinator=..., agents=..., integrations=...)`, and a
      workflow-level `@Eval`.
- [ ] `mkdocs.yml` — `nav:` extended with a `Tutorial:` section between
      `Quickstart` and `Reference`, ordered Overview → Step 1 → Step 2 →
      Step 3.
- [ ] `docs/next-steps.md` — remove the `Coming soon` placeholder for the
      tutorial; link the four new pages directly.
- [ ] `docs/index.md` — the homepage "Where to go next" grid gains a
      `Tutorial` card alongside `Quickstart` / `Install` / `Next steps`.
- [ ] Every code snippet validated against the current signatures of
      `@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Metric`, `@Workflow`,
      `@MCP` (cross-checked against the corresponding reference pages).
- [ ] `uv run mkdocs build --strict` passes locally.
- [ ] CI green: `Docs / Build site (mkdocs --strict)` workflow.

## Out of scope

- A standalone runnable example repo. That is AJ-50 (this tutorial unblocks
  it; this tutorial does not implement it).
- A demo video / animated gif. That is AJ-57 (public launch).
- New primitives, kwargs, or eval metrics. If a snippet wants a kwarg that
  does not exist, fix the snippet, not the framework.
- Translations (Spanish, etc.). v0.1 docs are English-only — see
  [`CLAUDE.md`](../CLAUDE.md) §Conventions.

## Implementation notes

- Page filenames use kebab-case (`step-1-hello.md`, not `step1.md`) — that
  is the convention the existing docs site already uses.
- For Step 2's JSONL dataset, show 2–3 sample lines inline; the reader
  creates `evals/support.jsonl` themselves. Do **not** check in a fake
  dataset under `docs/_assets/` — keep the docs tree prose-only.
- For Step 3's MCP block, prefer the GitHub MCP server (`stdio:` transport)
  because it requires only `GITHUB_PERSONAL_ACCESS_TOKEN` and works on any
  machine with `npx`.
- Code blocks should declare the language explicitly (` ```python `,
  ` ```bash `, ` ```jsonl `) so `pymdownx.highlight` renders them with the
  configured theme.
