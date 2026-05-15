# Tutorial — the 3-step killer demo arc

This tutorial takes you from the [Quickstart](../quickstart.md) finish line
to a **multi-agent, MCP-integrated, eval-guarded support system** — in
roughly **55 lines** of real code, written in three additive steps.

Each step builds on the previous one. The same `Support` class you write in
Step 1 is the agent that Step 2 evaluates and that Step 3 inlines as a
specialist inside a larger team.

## The arc

| Step                                          | Lines    | What it adds                                                                                                            |
| --------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------- |
| [1. Hello to prod](step-1-hello.md)           | ~12      | One agent, one tool, one streaming endpoint — with `fallback=`, `trace=True`, env validation and SSE wired in.          |
| [2. Evals — block regressions](step-2-evals.md) | +12      | An `@Eval` suite with `@Metric` methods that blocks PRs the moment your scores drop. Regression detection on every run. |
| [3. Equipo — multi-agent + MCP](step-3-team.md) | +30      | Three specialists routed by an LLM coordinator, with an `@MCP` integration block and a workflow-level `@Eval`.          |

Total: **~55 lines** for the full picture.

## Why this matters

Building an AI-native app the ad-hoc way means stitching together a web
framework, an LLM SDK, a streaming layer, a tool-call dispatcher, an
evaluation harness, prompt versioning, MCP transports, observability, and a
project layout. The same arc in the wild today is roughly **800 lines and
eight dependencies**.

Ajolopy ships all of that as one opinionated framework with [ten
primitives](../index.md#the-10-primitives). This tutorial exercises seven
of them end to end:

- [`@Agent`](../reference/agent.md) — the LLM-driven class.
- [`@Tool`](../reference/tool.md) — the function-calling capability.
- [`@Stream`](../reference/stream.md) — the SSE endpoint.
- [`@Eval`](../reference/eval.md) + `@Metric` — the regression suite.
- [`@Workflow`](../reference/workflow.md) — multi-agent orchestration.
- [`@MCP`](../reference/mcp.md) — external Model Context Protocol servers.

The remaining three ([`@Module`](../reference/module.md),
[`@Injectable`](../reference/injectable.md),
[`@Controller`](../reference/controller.md)) are framework primitives the
`ajolopy new` scaffolder wires for you on day one.

## Before you start

You should have finished the [Quickstart](../quickstart.md) so the
following are already in place:

- Python **3.14+** and [`uv`](https://docs.astral.sh/uv/) installed.
- A project on disk created with `ajolopy new my-agent` (we use the name
  `acme-support` in this tutorial — adjust paths to match yours).
- A working `ANTHROPIC_API_KEY` in `.env`.
- `ajolopy dev` runs cleanly and answers `curl` requests.

If any of those are not true, finish the [Quickstart](../quickstart.md)
first — it takes five minutes.

!!! tip "Run the steps in order"
    Every step in this arc patches the file produced by the previous step.
    Skipping ahead works for reading, but the diffs only make sense if you
    apply them on top of each other.

## Where to go next

Start with **[Step 1 — Hello to prod](step-1-hello.md)**.

When you finish Step 3 the tutorial closes the loop with pointers to:

- The [reference docs](../reference/index.md) for every kwarg you saw.
- The standalone
  [`examples/support-agent`](https://github.com/jcocano/Ajolopy/tree/main/examples/support-agent)
  example — the same arc as an installable repo you can fork (`AJ-50`).
- The [observability recipes](../next-steps.md#put-it-in-production)
  (Langfuse / Sentry / Grafana / Honeycomb / Datadog) once you want the
  `trace=True` data to land somewhere.
