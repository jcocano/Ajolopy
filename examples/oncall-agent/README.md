# `oncall-agent` — on-call assistant via `@MCP` + GitHub MCP server

This is the runnable example tracked as
[`AJ-63`](https://github.com/jcocano/Ajolopy/blob/main/specs/example-oncall-mcp.md).
It is the most opinionated demo of Ajolopy's `@MCP` primitive: a tiny
on-call agent that wires up the canonical
[`@modelcontextprotocol/server-github`](https://github.com/modelcontextprotocol/servers/tree/main/src/github)
server so the model can search issues, recent PRs, and commits on
behalf of an engineer triaging an incident.

After the steps below a reader has:

- An `OnCallAgent` answering streaming HTTP requests on `POST /chat`.
- One local `@Tool` (`summarize_request`) that normalises requests
  even when the MCP server is unhealthy.
- The GitHub MCP server attached via a single `@MCP` declaration —
  one of the only Python frameworks that exposes this as a
  first-class decorator.
- A 5-row `@Eval` suite with an LLM-as-judge metric and a
  deterministic reference-marker metric.
- Pre-generated `Dockerfile.prod` + `fly.toml` so the example can
  ship to production in one command.

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- An **`ANTHROPIC_API_KEY`** — grab one from
  [console.anthropic.com](https://console.anthropic.com/).
- *(optional)* A **`GITHUB_TOKEN`** — a fine-grained personal access
  token with read access to the repositories you want the agent to
  search. Without it, the MCP server stays unhealthy at boot, the
  rest of the example still runs, and the agent's local
  `summarize_request` tool still answers.
- *(optional, only at deploy time)* `npx` available in the runtime
  environment — required to actually spawn the GitHub MCP server
  over stdio.

This example is checked into the Ajolopy repository, so you do not
need a published `ajolopy` release: `pyproject.toml` points the
dependency at `../..` via `[tool.uv.sources]`.

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/oncall-agent
uv sync
cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY (GITHUB_TOKEN is optional)
```

Pull in the `[mcp]` extra to actually open a connection to the
GitHub MCP server:

```bash
uv sync --extra mcp
```

The decorator validates at import time without this extra; the
connection itself raises `MCPDependencyError` until it lands. The
agent's local tool still answers in both modes.

---

## Run the agent

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      oncall_agent.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "We are seeing a sustained spike of 502s on /events. Anything related in the repo?"}'
```

The response streams back token by token. With `GITHUB_TOKEN` set
and the `[mcp]` extra installed, the agent:

1. Calls `summarize_request` locally to lock in a service hint
   (``events``) and a severity guess (``high``).
2. Reaches into the GitHub MCP server via tools the framework
   discovered at boot — for example `github__search_issues` or
   `github__list_pull_requests` — to find related artifacts.
3. Streams back a concise triage: stated severity, supporting
   reference (issue / PR number), and the next concrete step.

Without `GITHUB_TOKEN`, the GitHub MCP server is marked unhealthy at
boot. The agent skips the namespaced MCP tools and answers using
only `summarize_request` plus the model's prior — useful for trying
the demo without a token.

> **Note — `@MCP` runtime requirements.** Spawning the GitHub MCP
> server happens at factory boot via `npx -y
> @modelcontextprotocol/server-github`. Make sure `npx` resolves on
> `$PATH` when you deploy — the framework logs a `WARN` and keeps
> serving if the spawn fails.

---

## Behind the wire

The example fits in three short files:

- `src/oncall_agent/integrations.py` — a five-line `@MCP` declaration
  for `GitHubMCP`. Empty class body; the decorator parses the server
  spec, validates the auth substitution, and stamps a single
  `_ajolopy_mcp` metadata attribute. The framework drains that
  registry at factory boot and discovers the server's tools.
- `src/oncall_agent/agents/oncall.py` — the `OnCallAgent` `@Agent`
  with `integrations=[GitHubMCP]`, one local `@Tool`
  (`summarize_request`), and a `@Stream("/chat")` handler taking
  `Annotated[ChatRequest, Body()]`. `summarize_request` runs locally
  and wins on any namespaced collision with an MCP tool.
- `src/oncall_agent/app_module.py` — the root `@Module` declaring
  only the agent. The `@MCP` class self-registers at decoration time,
  so it does **not** belong on the module's `providers=` list.

---

## Run the eval suite

`evals/oncall_eval.py` ships `OnCallEval` over the 5 rows in
`evals/oncall.jsonl`. Two metrics:

- **`identifies_severity`** — LLM-as-judge over the agent's answer.
  Penalises severity mismatches, generic responses, off-topic
  answers, and refusals to triage. Uses
  [`llm_judge`](../../docs/reference/eval.md) from
  `ajolopy.eval.metrics` (async, kwarg-only, cache-on).
- **`mentions_reference`** — deterministic per-case scorer (0.0 /
  1.0). Passes when the answer mentions at least one of the case's
  expected reference markers (service names, error codes, repo
  artifacts).

Run it from this example's root:

```bash
uv run ajolopy eval --ci
```

The CI form persists each run under `.ajolopy/eval-runs/` and
compares the next run against the previous baseline — the regression
detection described in
[`docs/tutorial/step-2-evals.md`](../../docs/tutorial/step-2-evals.md).

---

## Sample requests

`data/sample-requests.jsonl` ships five representative on-call
requests for spot-checking the agent during local development.
Pipe a line through `curl` to replay it against the running server:

```bash
uv run python -c "
import json, sys
with open('data/sample-requests.jsonl') as f:
    for i, line in enumerate(f, 1):
        print(f'{i}: {json.loads(line)[\"input\"]}')
"
```

---

## Smoke test

The example ships a single, fast, network-free `pytest`:

```bash
uv run pytest tests/
```

It only asserts the decorators land (`OnCallAgent.run`,
`summarize_request` carries the `@Tool` marker, `GitHubMCP` carries
the `@MCP` metadata stamp, `OnCallAgent` lists `GitHubMCP` in its
integrations, and the `@Stream("/chat")` route is registered). No
provider is called.

---

## Deploy

`Dockerfile.prod`, `.dockerignore`, and `fly.toml` are pre-generated
snapshots of the framework's `ajolopy deploy` CLI. Regenerate them
at any time:

```bash
uv run ajolopy deploy docker --force --out .
uv run ajolopy deploy fly --force --out .
```

Build and run the container locally:

```bash
docker build -f Dockerfile.prod -t oncall-agent:latest .
docker run -p 3000:3000 --env-file .env oncall-agent:latest
```

The base image is `python:3.14-slim`. If you want the GitHub MCP
server to come up inside the container, add a step that installs
Node.js (or pick a Debian-based image with `npx` preinstalled) — the
framework spawns `npx -y @modelcontextprotocol/server-github` over
stdio at boot, and that fails fast without a Node toolchain.

Deploy to Fly.io (requires `flyctl` installed and a Fly account):

```bash
flyctl launch --copy-config --name oncall-agent
flyctl secrets set ANTHROPIC_API_KEY=...
# Optional — set this only if your repos need GitHub access:
flyctl secrets set GITHUB_TOKEN=...
flyctl deploy
```

See [`docs/reference/cli-deploy.md`](../../docs/reference/cli-deploy.md)
for the full catalogue of `ajolopy deploy` targets.

---

## Layout

```
oncall-agent/
  README.md                       ← you are here
  .env.example                    ANTHROPIC_API_KEY + optional GITHUB_TOKEN
  pyproject.toml                  depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                 snapshot — `ajolopy deploy docker`
  .dockerignore                   snapshot — `ajolopy deploy docker`
  fly.toml                        snapshot — `ajolopy deploy fly`
  data/
    sample-requests.jsonl         5 representative on-call requests
  src/oncall_agent/
    __init__.py                   provider side-effect import
    main.py                       async def app() — `ajolopy dev` entry point
    app_module.py                 root @Module wiring OnCallAgent
    integrations.py               @MCP block declaring GitHubMCP
    agents/
      __init__.py
      oncall.py                   OnCallAgent — @Agent + @Tool + @Stream + integrations
  evals/
    oncall.jsonl                  5 sample rows for OnCallEval
    oncall_eval.py                @Eval(agent=OnCallAgent) + 2 @Metrics
  tests/
    conftest.py                   sets ANTHROPIC_API_KEY=test-dummy
    test_smoke.py                 decorator + MCP metadata; no provider calls
```

---

## Future enhancements

- **GitHub App auth.** Replace the personal access token with a
  GitHub App installation token; the `${GITHUB_TOKEN}` substitution
  can point at any secret you load at boot.
- **Pager integration.** A second `@MCP` block for an internal
  pager / on-call platform (PagerDuty MCP server, an internal MCP
  bridge over `mcp+sse`). The framework supports multiple servers
  per `@MCP` block — keys stay namespaced.
- **Workflow split.** Promote `OnCallAgent` into a `@Workflow` with
  separate `Triage` / `RepoLookup` / `Responder` specialists, each
  wired with the same `Integrations`. See
  [`examples/support-agent`](../support-agent/) for the multi-agent
  pattern.
- **Memory.** `@Agent(memory="redis://...")` for multi-turn triage
  conversations once a real chat UI sits in front of the endpoint.

---

## Where to go next

- The [`@MCP` reference](https://jcocano.github.io/Ajolopy/reference/mcp/)
  — every kwarg, the magical-default form, and the escape hatch
  (custom `MCPClient` subclass).
- The [3-step killer demo tutorial](https://jcocano.github.io/Ajolopy/tutorial/)
  — the prose companion to the `support-agent` example, the
  structural reference for this one.
- The [Ajolopy repository root README](../../README.md) — for
  contributing, the work board, and the project's design contract.
