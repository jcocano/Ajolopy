# `memory-assistant` — `@Agent(memory="redis://...")` end-to-end

This is the runnable companion to
[`AJ-64`](https://github.com/jcocano/Ajolopy/blob/main/specs/example-memory-redis.md).
It demonstrates the canonical "multi-turn in production" wiring: an
`@Agent` whose conversation transcript is persisted to Redis via the
magical `memory="redis://..."` URL kwarg, and a thin `Memory` subclass
that partitions history by a request-scoped `session_id`.

After the steps below a reader has:

- A `Tracker` agent answering streaming HTTP requests at `POST /chat`.
- One `@Tool` (`record_task`) keeping a per-session counter the model
  can quote back.
- A `Memory` escape hatch (`SessionScopedMemory`) showing how to keep
  the magical URL default while routing partitioning into a request
  context — that is the v0.1 pattern for per-user history under a
  single `@Agent` instance.

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- An **`ANTHROPIC_API_KEY`** — grab one from
  [console.anthropic.com](https://console.anthropic.com/).
- Docker (only required to run a local Redis; the smoke test does not
  need it).

This example is checked into the Ajolopy repository so you do not need
a published `ajolopy` release: `pyproject.toml` points the dependency
at `../..` via `[tool.uv.sources]` and pulls the `redis` extra so the
production memory backend is installed by default.

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/memory-assistant
uv sync
cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY
```

---

## Step 1 — start a local Redis

The example ships a tiny `docker-compose.yml` whose Redis service is
healthchecked and ready in a couple of seconds:

```bash
docker compose up redis -d
```

That binds Redis on `localhost:6379`. The default `REDIS_URL` in
`.env.example` matches.

> **Hosted Redis?** Any URL accepted by the `redis-py` SDK works —
> `redis://`, `rediss://` for TLS, with or without credentials.
> Update `REDIS_URL` in `.env` accordingly.

---

## Step 2 — run the agent

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      memory_assistant.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal, open **two** sessions — `alice` and `bob` — and
prove they are independent:

```bash
# Alice adds two tasks.
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "alice", "message": "Add call mom to my list."}'

curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "alice", "message": "Add submit expenses."}'

# Bob has none. Ask him.
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "bob", "message": "How many tasks do I have open?"}'

# Alice can still see hers.
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "alice", "message": "How many tasks do I have open?"}'
```

Bob's count answers zero; Alice's count answers two — even after
restarting the dev server, because both transcripts live in Redis.

What is happening under the hood:

- `@Agent(memory=os.environ.get("REDIS_URL", "memory://"))` resolves the
  URL through `ajolopy.memory.resolve_memory` and yields a
  `RedisMemory` (production) or `InMemoryMemory` (tests).
- The returned backend is wrapped in `SessionScopedMemory` before being
  passed to the decorator. The wrapper overrides `get`/`append`/`clear`
  to substitute the agent runtime's hardcoded `session_id="default"`
  with the value carried in a `ContextVar`.
- The `@Stream("/chat")` handler binds that `ContextVar` via
  `session_scope(body.session_id)` before delegating to `self.stream`
  — so every nested call (the runtime's memory reads, the
  `record_task` tool) sees the same session id.

That is the magical default plus the escape hatch in one screen.

---

## Step 3 — run the eval suite

```bash
uv run ajolopy eval --ci
```

`TrackerEval` is discovered automatically. The suite:

- Scores `Tracker` over five cases in `evals/tracker.jsonl`.
- Runs `addresses_intent` (LLM-as-judge) on every case's text.
- Runs `safe` (deterministic, `aggregator="min"`, `pass_threshold=1.0`)
  — a single forbidden token fails the whole metric.
- Runs `memory_isolation` (deterministic, `aggregator="min"`,
  `pass_threshold=1.0`) — two of the five rows simulate a
  prompt-injection attempt where the user pretends to be a different
  session and asks the agent to echo cross-session content. The metric
  fires on those rows; the other three score trivially `1.0`. A
  regression that makes the agent echo cross-session content drops the
  aggregate to zero.

The CI form (`ajolopy eval --ci`) also persists each run under
`.ajolopy/eval-runs/<timestamp>.json` and compares the next run against
it — that is the regression detection [`AJ-4`](../../docs/reference/eval.md)
documents.

---

## Step 4 — smoke test (no network, no Redis)

```bash
uv run pytest tests/
```

The smoke test:

- Asserts the `@Agent` / `@Tool` / `@Stream` decorators landed.
- Asserts the runtime's `memory` attribute is a `SessionScopedMemory`
  wrapping the in-memory backend (because `conftest.py` pins
  `REDIS_URL=memory://`).
- Exercises `session_scope` on a fresh `InMemoryMemory` instance and
  proves two scopes do not share state — that is the leak-prevention
  contract.

No provider call. No `monkeypatch` on the SDK. CI gates this
example by running `ruff`, `pyright`, and this `pytest` invocation only.

---

## Step 5 — deploy

The example ships pre-generated `Dockerfile.prod` + `.dockerignore` +
`fly.toml`. Regenerate any of them from the framework root with:

```bash
cd examples/memory-assistant
ajolopy deploy docker    # Dockerfile.prod + .dockerignore
ajolopy deploy fly       # fly.toml
```

To run the production image locally with a real Redis:

```bash
docker compose up --build
```

To deploy to Fly.io:

```bash
fly auth login
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set REDIS_URL=redis://...   # your hosted Redis
fly launch
fly deploy
```

The `fly.toml` exposes `/health` on port `3000` so Fly's TCP
healthcheck picks the app up automatically.

---

## Layout

```
memory-assistant/
  README.md                       ← you are here
  .env.example                    ANTHROPIC_API_KEY + REDIS_URL
  pyproject.toml                  depends on the local ajolopy[redis] via [tool.uv.sources]
  Dockerfile.prod                 rendered by `ajolopy deploy docker`
  .dockerignore                   rendered by `ajolopy deploy docker`
  docker-compose.yml              app + Redis services (hand-authored, see file header)
  fly.toml                        rendered by `ajolopy deploy fly`
  src/memory_assistant/
    __init__.py                   side-effect import for the Anthropic provider
    main.py                       async def app() — ajolopy dev entry point
    app_module.py                 @Module(agents=[Tracker])
    memory.py                     SessionScopedMemory + session_scope context manager
    agents/
      __init__.py
      tracker.py                  @Agent(memory=...) + @Tool + @Stream("/chat")
  data/
    sessions.jsonl                5 sample multi-turn rows across two sessions
  evals/
    tracker.jsonl                 5 cases; 2 of them exercise memory_isolation
    tracker_eval.py               @Eval(agent=Tracker) + 3 @Metrics
  tests/
    conftest.py                   pins ANTHROPIC_API_KEY=test-dummy + REDIS_URL=memory://
    test_smoke.py                 decorator + tool + memory-wrapper assertions
```

---

## Where to go next

- The [`@Agent` reference page](https://jcocano.github.io/Ajolopy/reference/agent/)
  documents every kwarg including the full `memory=` surface.
- The [Memory backend reference](https://jcocano.github.io/Ajolopy/reference/memory/)
  walks the five built-in backends (in-memory, Redis, Postgres, Mongo,
  SQLite) plus the `Memory` ABC contract the escape-hatch wrapper here
  rides on.
- The [Ajolopy repository root README](../../README.md) — for
  contributing, the work board, and the project's design contract.
