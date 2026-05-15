# `web-research` — an Ajolopy agent that searches the web via Tavily

This is the canonical "wire an external HTTP API as a `@Tool`" reference
for [Ajolopy](../../README.md), tracked as
[`AJ-65`](../../board.json). The agent answers research questions by
calling the [Tavily](https://tavily.com) search API through one `@Tool`,
then optionally composes a Markdown-cited answer through a second,
pure-Python `@Tool`. Two tools, one I/O + one pure-Python, so the
"composability" story is tangible.

- `@Agent` + `@Tool` + `@Stream` from the v0.1 surface.
- `httpx` for the Tavily REST call — no SDK dependency added.
- `@Eval` + `@Metric` with an LLM-as-judge regression suite plus a
  deterministic "contains URL" check.
- A pre-generated `Dockerfile.prod` + `fly.toml`, snapshotted from the
  framework's `ajolopy deploy` CLI.

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- An **`ANTHROPIC_API_KEY`** — grab one from
  [console.anthropic.com](https://console.anthropic.com/).
- A **`TAVILY_API_KEY`** — sign up at
  [tavily.com](https://tavily.com). The free tier (1k searches / month
  at the time of writing) is plenty for running the example end-to-end.

This example is checked into the Ajolopy repository so you do not need
a published `ajolopy` release: `pyproject.toml` points the dependency
at `../..` via `[tool.uv.sources]`.

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/web-research
uv sync
cp .env.example .env
# edit .env and paste both ANTHROPIC_API_KEY and TAVILY_API_KEY
```

---

## Run the agent

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      web_research.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the new features in Python 3.14?"}'
```

The response streams back token by token. Under the hood:

- **`@Agent`** is wired to `claude-sonnet-4-7`. The system prompt
  instructs the model to call `search_web(...)` first whenever a
  question needs up-to-date information, then optionally fold the
  results into a Markdown-cited answer through `format_citations(...)`.
- **`@Tool search_web`** delegates to a process-wide `TavilyClient`
  that posts to `https://api.tavily.com/search` with the
  `TAVILY_API_KEY` from your `.env`. The tool returns a list of
  `{title, url, snippet}` dicts ordered from most to least relevant.
- **`@Tool format_citations`** is pure Python — no I/O. It takes an
  answer string and the source list from `search_web` and returns a
  Markdown-footnoted version. Demonstrates **tool composition**:
  search → format.
- **`@Stream("/chat")`** mounts the method as an SSE endpoint with
  heartbeats and disconnect cancellation.

Two more questions worth trying from `data/sample-questions.jsonl`:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Who released the latest open-weights LLM and when?"}'

curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the current OpenTelemetry semantic convention for GenAI spans?"}'
```

> **Note — observability.** Both `@Agent` and `@Stream` emit
> OpenTelemetry spans always-on; backend selection happens at the SDK
> layer via standard OTel env vars
> (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`). Without
> `ajolopy[otel]` installed every span is a cheap no-op — no recording,
> no export.

---

## Why Tavily

[Tavily](https://tavily.com) is an AI-native search API: it returns
short snippets pre-scored for relevance, so the example skips the
result-page scraping step a generic search engine would force. One
endpoint (`POST /search`), one auth header. The example does **not**
abstract over Tavily — there is no `SearchProvider` ABC, no swap-in
alternative for Brave / Bing / Google CSE. The lesson is "wire a
third-party HTTP API as a `@Tool`"; the lesson is the same whichever
vendor you pick for your own app.

If you fork the example and want a different provider, replace
`src/web_research/tavily.py` with your own thin wrapper that exposes an
`async def search(query, max_results) -> list[dict[str, str]]`. The
agent's `search_web` tool only depends on that one method (see
`TavilyProtocol`); nothing else changes.

---

## Run the eval suite

`evals/researcher_eval.py` ships `ResearcherEval` over the rows in
`evals/researcher.jsonl`. Two metrics:

- **`cites_sources`** — LLM-as-judge. The criterion asks the judge to
  check that the answer addresses the user's question AND cites at
  least one concrete web source by URL. Penalises generic answers,
  off-topic answers, refusals to use `search_web`, and hallucinations.
- **`contains_url`** — deterministic per-case scorer. Passes when the
  answer text contains at least one `http://` or `https://` URL. A
  trivial regex check, but it catches the "model answered without
  citing anything" failure mode on every case, every run.

Run it from the example root:

```bash
uv run ajolopy eval --ci
```

The CI form persists each run under `.ajolopy/eval-runs/` and compares
the next run against the previous baseline — that is the regression
detection from
[`docs/tutorial/step-2-evals.md`](../../docs/tutorial/step-2-evals.md).

---

## Smoke test

The example ships a single, fast, **network-free** `pytest`:

```bash
uv run pytest tests/
```

It asserts the decorators land, the tools register, the Tavily wrapper
fails loudly on a missing API key, and `format_citations` round-trips
the fake search results into a Markdown-cited string. No real HTTP
call hits Tavily. The test seam:

```python
# tests/conftest.py
from web_research.tavily import set_client_for_tests

class FakeTavilyClient:
    async def search(self, query, max_results=5):
        return [{"title": "...", "url": "https://...", "snippet": "..."}]

set_client_for_tests(FakeTavilyClient())
```

The agent's `search_web` tool calls `get_client()`, which returns
whichever client was installed by `set_client_for_tests(...)`. Same
pattern as the docs-bot retriever singleton in
[`dogfood/docsbot/`](../../dogfood/docsbot/).

---

## How the HTTP-client injection seam works

`@Stream` mounts the agent class with `cls()` — there is no
constructor-injection seam at the route layer in v0.1. The pattern
this example uses, and that you should copy for any external-API
tool you wire up:

```python
# src/web_research/tavily.py
_client: TavilyProtocol | None = None

def get_client() -> TavilyProtocol:
    global _client
    if _client is None:
        _client = TavilyClient.from_env()
    return _client

def set_client_for_tests(client: TavilyProtocol | None) -> None:
    """Test seam — overrides the process-wide singleton."""
    global _client
    _client = client
```

The agent's `@Tool` reads the active client at call time:

```python
@Tool
async def search_web(self, query: str, max_results: int = 5):
    client = get_client()
    return await client.search(query, max_results=max_results)
```

In production, `get_client()` lazily builds a real `TavilyClient` from
the `TAVILY_API_KEY` env var. In tests, `conftest.py` installs a fake
that implements `TavilyProtocol` before the agent module is imported.
The fake records calls and returns a canned snippet list, so the
smoke test can assert tool routing and `format_citations` composition
without touching the network.

---

## Deploy

`Dockerfile.prod`, `.dockerignore`, and `fly.toml` are pre-generated
snapshots of the framework's `ajolopy deploy` CLI. Regenerate them at
any time:

```bash
uv run ajolopy deploy docker --force --out .
uv run ajolopy deploy fly --force --out .
```

Build and run the container locally:

```bash
docker build -f Dockerfile.prod -t web-research:latest .
docker run -p 3000:3000 --env-file .env web-research:latest
```

Deploy to Fly.io (requires `flyctl` installed and a Fly account):

```bash
flyctl launch --copy-config --name web-research
flyctl secrets set ANTHROPIC_API_KEY=... TAVILY_API_KEY=...
flyctl deploy
```

See [`docs/reference/cli-deploy.md`](../../docs/reference/cli-deploy.md)
for the full catalogue of `ajolopy deploy` targets.

---

## Layout

```
examples/web-research/
  README.md                      ← you are here
  .env.example                   ANTHROPIC_API_KEY + TAVILY_API_KEY placeholders
  pyproject.toml                 depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                snapshot — `ajolopy deploy docker`
  .dockerignore                  snapshot — `ajolopy deploy docker`
  fly.toml                       snapshot — `ajolopy deploy fly`
  data/
    sample-questions.jsonl       5 research prompts (the warm-up curl tour)
  src/web_research/
    __init__.py                  provider side-effect import
    main.py                      async def app() — ajolopy dev entry point
    app_module.py                root @Module — wires Researcher
    tavily.py                    httpx wrapper + process-wide singleton + test seam
    agents/
      __init__.py
      researcher.py              @Agent + @Tool search_web + @Tool format_citations + @Stream
  evals/
    researcher.jsonl             5 sample rows for ResearcherEval
    researcher_eval.py           @Eval(agent=Researcher) + 2 @Metrics
  tests/
    conftest.py                  installs FakeTavilyClient before tests collect
    test_smoke.py                decorator + tool + format_citations round-trip; no network
```

---

## Out of scope (deferred)

- Alternative search providers (Bing / Google CSE / Brave / SerpAPI).
  Tavily-only for v0.1.
- Result caching (Redis / in-memory LRU). Adds complexity unrelated to
  the wedge lesson.
- Multi-turn research with `@Agent(memory="redis://...")`. Stateless
  per request keeps the example focused on tool wiring.
- Re-ranking or chunking of returned snippets — Tavily already returns
  scored snippets.
- A real production rate-limit / retry / circuit-breaker. Readers can
  add their own resilience layer.

---

## Where to go next

- The [reference docs](https://jcocano.github.io/Ajolopy/reference/) —
  one page per primitive used in this example.
- The [3-step killer demo tutorial](https://jcocano.github.io/Ajolopy/tutorial/)
  and its runnable companion at
  [`examples/support-agent`](../support-agent/).
- The [`dogfood/docsbot`](../../dogfood/docsbot/) — an agent that does
  RAG over the framework's own docs, using the same `@Tool` + singleton
  pattern this example uses for the Tavily client.
- The [Ajolopy repository root README](../../README.md) for
  contributing and the project's design contract.
