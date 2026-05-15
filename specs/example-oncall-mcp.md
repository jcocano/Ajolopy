# AJ-63 — Example: on-call agent via `@MCP` (GitHub MCP server)

> Status: backlog → ready · Type: docs · Priority: p1 · Milestone: v0.1
> Blocks: — · Blocked by: —
> Related: AJ-50 (the support-agent example — structural reference),
> AJ-54 (the docsbot dogfood — pattern reference),
> AJ-7 (the `@MCP` primitive itself).

## Goal

Ship a fork-and-run example that puts the `@MCP` primitive at the
centre of the demo. After this lands a reader can:

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/oncall-agent
uv sync
cp .env.example .env  # paste ANTHROPIC_API_KEY, optionally GITHUB_TOKEN
ajolopy dev
```

…and `POST /chat` with a request like
*"we're seeing 502s on `/events`, anything related in the repo?"* and
get a triage response that, when `GITHUB_TOKEN` is set, leverages the
GitHub MCP server to surface related issues / recent PRs / commits.

`@MCP` is one of the highest-differentiation primitives in Ajolopy —
the Python ecosystem ships nothing equivalent as a first-class
decorator. AJ-50 already exercises `@MCP` inside a larger team demo;
AJ-63 surfaces it as the **headline primitive** of a small, focused
example, so a new reader does not have to wade through the workflow
layer to see how it lands.

## Why this matters

- The GitHub MCP server is the canonical "real-world" MCP server most
  AI engineers will reach for first — using it in the demo proves the
  framework integrates with the external MCP ecosystem, not just with
  Ajolopy's own `@MCPServer` toy servers.
- The example highlights the **local-`@Tool` + MCP-tool coexistence**
  rule documented in `docs/reference/mcp.md`: local tools always win
  on a namespaced collision. The on-call agent ships a local
  `summarize_request` `@Tool` alongside the GitHub MCP tools so the
  README can point at both classes of tools side-by-side.
- The example boots **cleanly without** `ajolopy[mcp]` installed or a
  `GITHUB_TOKEN` set — the MCP server stays unhealthy, the agent's
  local tool still answers. This shows that `@MCP` is a soft
  dependency, not a tripwire.

## Structure

The example lives under `examples/oncall-agent/` at the repository
root, mirroring the AJ-50 layout one-to-one:

```
examples/oncall-agent/
  README.md                          install / env / run / eval / deploy walkthrough
  .env.example                       ANTHROPIC_API_KEY + optional GITHUB_TOKEN
  pyproject.toml                     depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                    snapshot — `uv run ajolopy deploy docker`
  .dockerignore                      snapshot — `uv run ajolopy deploy docker`
  fly.toml                           snapshot — `uv run ajolopy deploy fly`
  data/
    sample-requests.jsonl            5 representative on-call requests
  src/oncall_agent/
    __init__.py                      provider side-effect import + module docstring
    main.py                          async def app() — `ajolopy dev` entry point
    app_module.py                    root @Module wiring OnCallAgent
    integrations.py                  @MCP block declaring the GitHub MCP server
    agents/
      __init__.py
      oncall.py                      OnCallAgent — @Agent + @Tool + @Stream + integrations
  evals/
    oncall.jsonl                     5 sample rows for OnCallEval
    oncall_eval.py                   @Eval(agent=OnCallAgent) + 2 @Metrics
  tests/
    conftest.py                      sets ANTHROPIC_API_KEY=test-dummy before collection
    test_smoke.py                    decorator + MCP block metadata; no provider calls
```

## The `@MCP` block

```python
@MCP(
    servers={"github": "stdio:npx -y @modelcontextprotocol/server-github"},
    auth={"github": {"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}}},
)
class GitHubMCP: ...
```

- The server key (`"github"`) becomes the namespace prefix for every
  discovered tool (e.g. `github__search_issues`). Local `@Tool`
  methods on `OnCallAgent` keep their bare names and win on
  collisions.
- The auth spec uses the `${GITHUB_TOKEN}` substitution — resolved at
  factory boot against `os.environ`. Missing means the server is
  marked unhealthy; the workflow still serves.

`GitHubMCP` is referenced from `OnCallAgent` via
`integrations=[GitHubMCP]`. It is **not** added to the module's
`providers=` list — `@MCP`-decorated classes self-register into the
process-wide MCP registry at decoration time, which the factory
drains at boot.

## The agent

```python
@Agent(
    model="claude-sonnet-4-7",
    system=(
        "You are an engineering on-call assistant. "
        "For any incoming request, call summarize_request first to "
        "normalise the user's report, then use the GitHub MCP tools to "
        "look up related issues, recent PRs, or commits. Propose a "
        "concise triage with severity (low/medium/high) and the next "
        "concrete step."
    ),
    fallback="claude-haiku-4-5",
    integrations=[GitHubMCP],
)
class OnCallAgent:
    @Tool
    async def summarize_request(self, message: str) -> dict[str, str]:
        ...

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[str]:
        ...
```

`summarize_request` is a deterministic stub: it extracts a rough
service hint and severity guess so the example proves the local tool
boots even with the MCP server unhealthy. Production on-call agents
would replace it with a real classifier.

## Eval suite

`evals/oncall_eval.py` runs against `evals/oncall.jsonl` (5 rows,
threshold 0.6) with two metrics:

- `identifies_severity` — `llm_judge` from `ajolopy.eval.metrics`.
  Scores the agent's answer against
  *"correctly identifies the severity (low / medium / high) implied
  by the request"*.
- `mentions_reference` — deterministic per-case scorer (0.0 / 1.0).
  Passes when the answer mentions at least one of the expected
  reference markers (`expected.must_contain_any`) from the case row.

Both metrics share the suite signature `(self, output, expected)` so
the framework's runner can score them in a uniform sweep.

## Sample dataset

`data/sample-requests.jsonl` ships five representative on-call
requests — covering high-severity prod incidents, suspected
regressions referencing recent PRs, integration questions about
GitHub workflows, low-severity questions, and triage requests that
should call out missing detail. The same row shape feeds the eval
dataset under `evals/oncall.jsonl`.

## Acceptance criteria

- [ ] `examples/oncall-agent/` exists with the structure documented above.
- [ ] `examples/oncall-agent/src/oncall_agent/integrations.py` declares
      `GitHubMCP` with the canonical
      `stdio:npx -y @modelcontextprotocol/server-github` server spec
      and `${GITHUB_TOKEN}` auth substitution.
- [ ] `examples/oncall-agent/src/oncall_agent/agents/oncall.py` defines
      `OnCallAgent` (`@Agent`) with a local `summarize_request` `@Tool`,
      `integrations=[GitHubMCP]`, `fallback="claude-haiku-4-5"`, and a
      `@Stream("/chat")` handler taking
      `Annotated[ChatRequest, Body()]`.
- [ ] `examples/oncall-agent/evals/oncall_eval.py` declares
      `OnCallEval` with `threshold=0.6`, an `llm_judge` metric
      (`identifies_severity`) and a deterministic metric
      (`mentions_reference`).
- [ ] `examples/oncall-agent/evals/oncall.jsonl` ships **5** rows in
      the shape the metrics expect.
- [ ] `examples/oncall-agent/data/sample-requests.jsonl` ships **5**
      representative on-call requests.
- [ ] `examples/oncall-agent/pyproject.toml` declares
      `[tool.uv.sources] ajolopy = { path = "../..", editable = true }`
      and lists `ajolopy[mcp]` as an optional dependency.
- [ ] `examples/oncall-agent/.env.example` lists
      `ANTHROPIC_API_KEY=` and `GITHUB_TOKEN=` (optional).
- [ ] `examples/oncall-agent/README.md` walks install → env → run →
      curl `/chat` → eval → deploy, and explicitly documents the
      no-token graceful-degradation behaviour.
- [ ] `examples/oncall-agent/tests/test_smoke.py` asserts decorator
      metadata, MCP block presence, the `/chat` route registration,
      and tool registration without calling any provider.
- [ ] `examples/oncall-agent/Dockerfile.prod` + `.dockerignore` +
      `fly.toml` are pre-generated via
      `uv run ajolopy deploy docker --force --out .` and
      `uv run ajolopy deploy fly --force --out .`.
- [ ] Root `pyproject.toml` adds
      `examples/oncall-agent/` to pyright `executionEnvironments`
      and ruff `per-file-ignores` (mirroring the AJ-50 / AJ-54 entries).
- [ ] Root `README.md` extends the `## Examples` section to list
      `examples/oncall-agent/` with a one-paragraph blurb.
- [ ] `docs/next-steps.md` adds a bullet under *Read real projects*
      linking the example at its GitHub URL.
- [ ] `uv run ruff check examples/oncall-agent src/ajolopy` — clean.
- [ ] `uv run ruff format --check examples/oncall-agent` — clean.
- [ ] `uv run pyright examples/oncall-agent` — 0 errors.
- [ ] `uv run pyright` (full repo) — no new errors vs `main`.
- [ ] `uv run pytest tests/` (full repo) — green.
- [ ] `cd examples/oncall-agent && uv sync && uv run pytest tests/` — green.
- [ ] `uv run --group docs mkdocs build --strict` — passes.

## Out of scope

- A GitHub App registration flow. The example reads a personal access
  token from the environment; turning it into a production-grade
  GitHub App is a future enhancement.
- A real on-call escalation pipeline (PagerDuty / Opsgenie webhooks,
  paging schedules, SLA tracking). The example demonstrates the
  `@MCP` ingest side; the egress side is post-v0.1.
- A second MCP server (Linear, Slack, …). `GitHubMCP` keeps the
  surface tight; readers can copy the pattern for additional servers.
- Translations. v0.1 example app is English-only.

## Implementation notes

- **API drift between Brief and current source.** `@Agent` does **not**
  accept `trace=` in v0.1; OTel instrumentation is always-on (no-op
  without the `otel` extra). The example does not pass `trace=`.
- **`@MCP` is declared but the GitHub MCP server is optional at
  runtime.** Without `ajolopy[mcp]` + `GITHUB_TOKEN`, the MCP layer
  marks the server unhealthy and the agent's local
  `summarize_request` tool still answers — README documents this.
- **Path-based ajolopy dep.** `[tool.uv.sources] ajolopy = { path = "../..",
  editable = true }` keeps the example self-contained inside the repo
  so `uv sync` works on a fresh clone — no published PyPI release
  required while v0.1 is in development.
- **Tests are decorator-metadata-only.** No `pytest.mark.anyio`
  plumbing, no monkeypatching the Anthropic SDK or the MCP transport.
  The smoke test exercises `hasattr(OnCallAgent, "run")`,
  `hasattr(OnCallAgent, "stream")`, the `@Tool` markers, the `@MCP`
  metadata on `GitHubMCP`, and the `/chat` route registration —
  enough to catch import-time regressions, not enough to depend on
  network or env.
