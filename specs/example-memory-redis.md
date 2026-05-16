# AJ-64 — Example: persistent assistant with `@Agent(memory="redis://...")`

> Status: backlog → ready · Type: docs · Priority: p1 · Milestone: v0.1
> Blocks: AJ-57 follow-on (post-launch examples expansion).
> Blocked by: none (AJ-24 Memory ABC + AJ-50 example layout shipped).

## Goal

Ship the **canonical "multi-turn in production" reference** under
`examples/memory-assistant/`. Every real production AI app needs
conversation memory — and `@Agent(memory="redis://...")` is one of the
nicest ergonomics in the framework: the magical default is a URL string,
the escape hatch is a `Memory` subclass.

After this lands, a reader can:

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/memory-assistant
uv sync
docker compose up redis -d
cp .env.example .env  # set ANTHROPIC_API_KEY
ajolopy dev
```

…and curl `/chat` twice with two different `session_id` values and see
the assistant remember each session's task list independently.

## Scenario

A small personal task-tracking assistant. The user adds tasks, asks how
many are open, asks to clear them. The agent keeps the running list in
Redis so the conversation survives process restarts and scales across
worker processes.

- One `@Agent` (`Tracker`): `model="claude-opus-4-7"`,
  `memory="redis://..."`, `system="You are a personal task tracker."`
- One `@Tool` (`record_task`): appends a task description to the user's
  session-scoped list and returns the new count.
- One `@Stream("/chat")` endpoint: `Annotated[ChatRequest, Body()]` with
  `session_id` and `message` fields.

## URL-driven Memory configuration

The decorator reads the URL from the environment at module-import time
(via `os.environ.get("REDIS_URL", "memory://")`) and the resolver picks
the matching backend:

| `REDIS_URL` value             | Backend instantiated                       |
|-------------------------------|--------------------------------------------|
| `redis://localhost:6379/0`    | `RedisMemory` (production)                 |
| `rediss://...`                | `RedisMemory` over TLS                     |
| `memory://`                   | `InMemoryMemory` (tests + dev fallback)    |

`memory://` is the in-memory fallback so the smoke test never needs a
running Redis server. The README documents the upgrade path: `pip
install ajolopy[redis]` and flip `REDIS_URL`.

## Session-id flow

`AgentRuntime` v0.1 uses a single internal `_DEFAULT_SESSION_ID =
"default"` when it calls `memory.get / append / clear` — the per-call
`run(message)` / `stream(message)` signature does not yet carry a
`session_id` kwarg through. That mirrors the design contract: the
example demonstrates session isolation **at the Memory layer**, using a
`Memory` subclass that overrides every method to remap the incoming
`session_id` to the value carried in a `ContextVar[str]`.

That is the canonical "escape hatch" for the magical default — and the
example showcases it explicitly:

- `SessionScopedMemory(Memory)` wraps an inner `Memory` instance.
- A `ContextVar[str]` (`current_session`) is set by the `@Stream("/chat")`
  handler from the request body **before** delegating to
  `self.stream(body.message)`.
- Every `get / append / clear` call replaces the agent runtime's hardcoded
  `"default"` key with the contextvar's current value.

Net result: two different requests with different `session_id` values
share the same Redis instance and the same agent instance, but the
transcript Redis sees is partitioned by session.

## Layout

```
examples/memory-assistant/
  README.md                       # install → redis → run → curl → eval → deploy
  .env.example                    # ANTHROPIC_API_KEY + REDIS_URL
  pyproject.toml                  # depends on the local ajolopy[redis]
  Dockerfile.prod                 # rendered via `ajolopy deploy docker`
  .dockerignore                   # rendered via `ajolopy deploy docker`
  fly.toml                        # rendered via `ajolopy deploy fly`
  docker-compose.yml              # app + redis (hand-authored from the AJ-41 helper)
  src/memory_assistant/
    __init__.py                   # side-effect import for the Anthropic provider
    main.py                       # async def app() — ajolopy dev entry point
    app_module.py                 # @Module(agents=[Tracker])
    memory.py                     # SessionScopedMemory — the escape-hatch wrapper
    agents/
      __init__.py
      tracker.py                  # @Agent(memory=...) + @Tool + @Stream("/chat")
  data/
    sessions.jsonl                # 5 sample multi-turn rows
  evals/
    tracker.jsonl                 # 5 rows — two of them tagged for the leak metric
    tracker_eval.py               # @Eval(agent=Tracker) + 3 @Metrics
  tests/
    conftest.py                   # sets ANTHROPIC_API_KEY=test-dummy + REDIS_URL=memory://
    test_smoke.py                 # decorator + tool + memory wrapper assertions
```

## Eval suite

`evals/tracker.jsonl` carries five cases. The metrics:

- **`addresses_intent`** — LLM-judge over the response text against
  `expected.criterion`. Standard Step-2-style metric.
- **`safe`** — deterministic, `aggregator="min"`, `pass_threshold=1.0`:
  the answer must never contain any token in `expected.must_not_contain`.
- **`memory_isolation`** — deterministic, `aggregator="min"`,
  `pass_threshold=1.0`: a case tagged `expected.leak_marker="alpha-task"`
  asserts the answer does **not** mention that marker even though the
  underlying Redis instance has stored it under a different session_id.
  This is what makes the example useful as a regression test against
  session leakage.

The two leak-prevention rows use distinct `session_id` values in the
case payload; the eval driver feeds each through the agent and asserts
no marker bleeds across.

## Pre-generated deploy artefacts

- `Dockerfile.prod` + `.dockerignore` — rendered with
  `ajolopy deploy docker` from inside the example directory.
- `fly.toml` — rendered with `ajolopy deploy fly`. App name:
  `memory-assistant`.
- `docker-compose.yml` — hand-authored using the AJ-41
  `render_docker_compose(databases=("redis",))` helper as a starting
  point, then trimmed to keep only the app + redis services and a
  comment explaining that `ajolopy deploy docker` regenerates the
  Dockerfile.prod referenced by the `app` service build.

The README walks the reader through `docker compose up redis -d` first
(the fastest way to a real Redis on a dev machine) before flipping
`REDIS_URL` and starting `ajolopy dev`.

## Acceptance criteria

- [ ] `examples/memory-assistant/` exists with the layout above.
- [ ] `examples/memory-assistant/src/memory_assistant/agents/tracker.py`
      declares `@Agent(memory=os.environ.get("REDIS_URL", "memory://"))`
      with a `record_task` `@Tool` and a `@Stream("/chat")` endpoint
      whose body is `Annotated[ChatRequest, Body()]` with a required
      `session_id: str` and `message: str`.
- [ ] `examples/memory-assistant/src/memory_assistant/memory.py` defines
      a `SessionScopedMemory(Memory)` subclass that delegates `get /
      append / clear` to an inner backend after substituting the
      `session_id` with the current `ContextVar` value, plus a
      `session_scope(value: str)` context manager helper.
- [ ] `examples/memory-assistant/pyproject.toml` declares
      `ajolopy[redis]` via `[tool.uv.sources] ajolopy = { path = "../..",
      editable = true, extras = ["redis"] }`.
- [ ] `examples/memory-assistant/.env.example` ships with
      `ANTHROPIC_API_KEY=` and `REDIS_URL=redis://localhost:6379/0`.
- [ ] `examples/memory-assistant/docker-compose.yml` declares an `app`
      service and a `redis` service with healthcheck — both bound to a
      shared network. The `app` service references the example's
      pre-generated `Dockerfile.prod`.
- [ ] `examples/memory-assistant/Dockerfile.prod` and `.dockerignore`
      are present and match the canonical render of
      `ajolopy deploy docker`.
- [ ] `examples/memory-assistant/fly.toml` is present and matches the
      canonical render of `ajolopy deploy fly` (app name
      `memory-assistant`).
- [ ] `examples/memory-assistant/data/sessions.jsonl` contains five
      multi-turn rows simulating two different sessions.
- [ ] `examples/memory-assistant/evals/tracker.jsonl` contains five
      cases with at least two rows exercising the
      `memory_isolation` metric across distinct `session_id` values.
- [ ] `examples/memory-assistant/evals/tracker_eval.py` declares
      `@Eval(agent=Tracker, dataset="evals/tracker.jsonl", threshold=0.85)`
      and three `@Metric`s: `addresses_intent` (LLM-judge), `safe`
      (deterministic min-aggregated), `memory_isolation` (deterministic
      min-aggregated).
- [ ] `examples/memory-assistant/tests/test_smoke.py` exercises the
      decorator + tool + memory wrapper without calling any provider
      and without requiring a running Redis (uses `REDIS_URL=memory://`
      set in `conftest.py`).
- [ ] `examples/memory-assistant/README.md` walks install → run Redis
      (`docker compose up redis -d`) → set env → run → two `curl`
      calls with different `session_id`s → eval → deploy. Voice matches
      the AJ-50 `support-agent` README.
- [ ] Repository root `README.md` `## Examples` section adds a third
      bullet pointing at `examples/memory-assistant/`.
- [ ] `docs/next-steps.md` `## Read real projects` section adds a
      bullet pointing at the same GitHub URL.
- [ ] Repository root `pyproject.toml` `[tool.pyright]
      executionEnvironments` adds an entry for
      `examples/memory-assistant` and its `tests/` sub-tree (mirroring
      the AJ-50 example).
- [ ] Repository root `pyproject.toml` `[tool.ruff.lint.per-file-ignores]`
      gains an entry for `examples/memory-assistant/tests/**` mirroring
      the support-agent example.
- [ ] `uv run --group docs mkdocs build --strict` passes locally.
- [ ] `uv run ruff check examples/memory-assistant` passes with zero
      violations.
- [ ] `uv run ruff format --check examples/memory-assistant` passes.
- [ ] `uv run pyright examples/memory-assistant` passes (strict).
- [ ] From inside the example directory:
      `cd examples/memory-assistant && uv sync && uv run pytest tests/`
      passes (smoke test only — no real Redis, no provider call).

## Out of scope

- Per-user authentication of `session_id`. Production systems gate the
  client-supplied id against an auth token; this example trusts the
  client. v0.2+ surfaces.
- Configurable per-user TTLs / message-window pruning. `RedisMemory`
  v0.1 stores transcripts indefinitely.
- Postgres / MongoDB / SQLite variants. The example is **the Redis
  reference**; the README mentions the alternative URL schemes once and
  links the `Memory` reference page.
- Production-grade session-id propagation through `WebSocket` /
  multi-tenant request scopes. The example uses one `ContextVar`; the
  pattern composes onto a request middleware in the AJ-46
  `@UseGuards`-style story, not here.
- Embedded RAG / semantic memory. AJ-62 covers retrievers; this example
  is chat-history only.

## Implementation notes

- **`AgentRuntime` session_id constraint.** The v0.1 agent runtime
  hardcodes `_DEFAULT_SESSION_ID = "default"` when it calls
  `memory.get / append / clear`. The example does NOT change the
  framework; it demonstrates how to bridge that with a one-screen
  `SessionScopedMemory` wrapper backed by a `ContextVar`. That is the
  canonical illustration of the "default magical + escape hatch"
  pattern for `Memory`.
- **Side-effect provider import.** `src/memory_assistant/__init__.py`
  imports `ajolopy.providers.anthropic` for its side-effect
  registration — same pattern as the AJ-50 example.
- **No `trace=` kwarg.** OpenTelemetry instrumentation is always on in
  v0.1; the example honours the current API.
- **Smoke test, not integration test.** The example's `pytest`
  intentionally never opens a TCP socket to Redis. CI gates the example
  via `ruff` + `pyright` + the smoke test only — same contract as the
  AJ-50 example.
- **`docker-compose.yml` is hand-authored.** The AJ-41 helper
  (`render_docker_compose(databases=("redis",))`) emits a development
  compose that targets the Dockerfile's `development` stage; this
  example uses `Dockerfile.prod` (no dev stage), so the compose is
  trimmed by hand and a comment in the file points readers at
  `ajolopy deploy docker` for re-generation.
