# `support-agent` — the runnable companion to the killer-demo tutorial

This is the standalone, forkable example application referenced by
[`AJ-50`](https://github.com/jcocano/Ajolopy/blob/main/specs/docs-example-support.md).
It materialises every snippet from the
[`3-step killer demo tutorial`](https://jcocano.github.io/Ajolopy/tutorial/)
(`AJ-48`) as actual Python on disk.

After the steps below a reader has a `Support` agent answering streaming
HTTP requests, an `@Eval` suite that runs in CI, and a three-specialist
`@Workflow` routed by an LLM coordinator — every primitive from the
tutorial except `@Module` / `@Injectable` / `@Controller`, which are
already wired by the surrounding scaffold.

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- An **`ANTHROPIC_API_KEY`** — grab one from
  [console.anthropic.com](https://console.anthropic.com/).

This example is checked into the Ajolopy repository so you do not need a
published `ajolopy` release: `pyproject.toml` points the dependency at
`../..` via `[tool.uv.sources]`.

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/support-agent
uv sync
cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY
```

## Pick a mode

The example wires either Step 1's single agent or Step 3's full team
depending on `SUPPORT_AGENT_MODE`:

| Mode      | What runs                                           | Default? |
|-----------|-----------------------------------------------------|----------|
| `team`    | The Step 3 `SupportTeam` workflow on `/chat`.       | yes      |
| `single`  | The Step 1 single `Support` agent on `/chat`.       |          |

Flip via `.env`:

```bash
SUPPORT_AGENT_MODE=single   # or "team"
```

---

## Step 1 — single `Support` agent

Start with `SUPPORT_AGENT_MODE=single` in your `.env`, then:

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      support_agent.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is order 4392? Use the tool."}'
```

The response streams back token by token. The agent calls
`lookup_order("4392")`, gets the stubbed answer
(`status=in_transit, eta=tomorrow`), and folds it into its reply. That is
the round trip for **Step 1**:

- **`@Agent`** registered `Support` with the DI container, validated the
  Anthropic provider env at boot, and wired the `fallback="claude-haiku-4-5"`
  retry policy.
- **`@Tool`** synthesised the JSON Schema for `lookup_order` and dispatched
  the function-calling loop.
- **`@Stream("/chat")`** mounted the method as an SSE endpoint with
  heartbeats and disconnect cancellation.

> **Note — observability.** The tutorial mentions `trace=True` on
> `@Agent`. In the v0.1 source the kwarg has been removed; OpenTelemetry
> instrumentation is always-on and cheap when no SDK is installed. The
> example honours the current API.

---

## Step 2 — block PRs that regress your quality

The `evals/` directory ships a `SupportEval` suite plus a tiny JSONL
dataset. Run it from the example root:

```bash
uv run ajolopy eval --ci
```

`SupportEval` is discovered automatically. The suite:

- Scores `Support` over the three cases in `evals/support.jsonl`.
- Runs the LLM-as-judge `helpful` metric on the answer text.
- Runs the deterministic `safe` metric over every case — a single
  forbidden token fails the whole metric (`aggregator="min"`,
  `pass_threshold=1.0`).
- Exits non-zero if the aggregate score drops below `threshold=0.85`
  **or** a metric breaks its `pass_threshold`.

The CI form (`ajolopy eval --ci`) also persists the run under
`.ajolopy/eval-runs/<timestamp>.json` and compares the next run against
it — that is the **regression detection** the tutorial walks through.

---

## Step 3 — multi-agent + MCP, no client rewrites

Keep `SUPPORT_AGENT_MODE=team` (the default) and restart `ajolopy dev`.
The wire contract is identical — clients hit the same `POST /chat`. What
changes is what happens behind it:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Refund order 4392, the package was damaged.", "user_id": "u_42"}'
```

The response now streams **JSON events** instead of raw tokens. A healthy
run yields four event types:

```
data: {"type": "handoff", "to": "Billing"}

data: {"type": "agent_result", "content": "Refund issued for order 4392.", "is_error": false}

data: {"type": "done"}
```

What is happening on the server side:

- **`@Workflow(coordinator="claude-sonnet-4-7", ...)`** built a routing LLM
  that exposes `Triage`, `Billing`, and `Technical` as tools. The
  coordinator picks one, hands off, and the chosen specialist answers.
- **`@MCP`** (the `Integrations` class) declared the GitHub MCP server
  over stdio. At factory boot, the framework spawns
  `npx -y @modelcontextprotocol/server-github`, discovers its tools, and
  injects them into every specialist's tool list.
- The Step 3 `evals/team_eval.py` adds a workflow-level `@Eval` —
  `addresses_intent` (LLM-judge) plus `mentions_domain` (deterministic).
  `ajolopy eval --ci` picks it up alongside `SupportEval`.

> **Note — `@MCP` runtime requirements.** Connecting to the GitHub MCP
> server requires the `ajolopy[mcp]` extra and a `GITHUB_TOKEN` in `.env`.
> Without those the decorator still validates at import time and the
> workflow still serves — the server simply stays unhealthy and its
> tools are not advertised.

---

## Smoke test

The example ships a single, fast, network-free `pytest`:

```bash
uv run pytest tests/
```

It only asserts the decorators land (`Support.run`, `Billing.issue_refund`
carries the `@Tool` marker, the workflow exposes `stream`, the MCP block
carries metadata). No provider is called.

---

## Layout

```
support-agent/
  README.md                     ← you are here
  .env.example                  ANTHROPIC_API_KEY + optional GITHUB_TOKEN
  pyproject.toml                depends on the local ajolopy via [tool.uv.sources]
  src/support_agent/
    __init__.py
    main.py                     async def app() — ajolopy dev entry point
    app_module.py               @Module wiring (Step 1 vs Step 3 toggled by env)
    agents/
      __init__.py
      support.py                Step 1 — single @Agent + @Tool + @Stream
      team.py                   Step 3 — Triage / Billing / Technical + @MCP + @Workflow
  evals/
    support.jsonl               sample rows for SupportEval
    support_eval.py             Step 2 — @Eval(agent=Support) + 2 @Metrics
    support_team.jsonl          sample rows for TeamEval
    team_eval.py                Step 3 — @Eval(workflow=SupportTeam) + 2 @Metrics
  tests/
    test_smoke.py               decorator metadata only — no provider calls
```

---

## Where to go next

- The [tutorial overview](https://jcocano.github.io/Ajolopy/tutorial/) —
  the prose companion to this example.
- The [reference docs](https://jcocano.github.io/Ajolopy/reference/) —
  one page per primitive, with every kwarg, the magical default, and the
  escape-hatch subclass pattern.
- The [Ajolopy repository root README](../../README.md) — for
  contributing, the work board, and the project's design contract.
