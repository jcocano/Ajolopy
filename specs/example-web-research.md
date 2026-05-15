# AJ-65 — Example: web research agent (Tavily @Tool integration)

> Status: backlog → ready · Type: docs · Priority: p1 · Milestone: v0.1
> Blocks: — (launch examples expansion).
> Blocked by: — (no open dependencies; uses primitives already shipped).

## Goal

Ship the canonical "wire an external HTTP API as a `@Tool`" reference. The
existing `examples/support-agent/` shows a stubbed tool; the `dogfood/docsbot/`
shows a retriever subclass. Neither demonstrates the most common production
pattern: **the agent calls a real third-party REST API, in this case the
[Tavily](https://tavily.com) web search API, through one `@Tool` method.**

After this lands, a reader can:

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/web-research
uv sync
cp .env.example .env  # set ANTHROPIC_API_KEY + TAVILY_API_KEY
ajolopy dev
```

…and query a research assistant that, given a question like "what's new in
Python 3.14?", calls Tavily's search endpoint, gets fresh URLs + snippets,
and streams an answer with citations.

The example covers the most-asked production question — "how do I plug an
HTTP API into an agent?" — without invoking Bing/Google/Brave (those are
deferred to post-v0.1) and without any caching layer (also deferred).

## Why Tavily

- **AI-native search API by design.** Returns short snippets + URLs already
  scored for relevance; no result-page scraping required. Matches the
  common-case "RAG over fresh web pages" shape better than generic search.
- **Single endpoint, single auth header.** `POST https://api.tavily.com/search`
  with the API key in the JSON body. Trivial to demonstrate from a single
  `httpx` POST — no SDK dependency added to the example.
- **Generous free tier** (1k searches/month at the time of writing) — readers
  can run the example end-to-end without a paid plan.
- **MIT-compatible from the framework's perspective** — we do not bundle a
  Tavily SDK; we call their public REST endpoint with `httpx` (which the
  framework already ships as a transitive dev dep).

The example does **not** abstract over Tavily — there is no
`SearchProvider` ABC, no swap-in alternative for Brave/Bing. The lesson is
"wire a third-party HTTP API as a `@Tool`"; the lesson is the same whichever
vendor a reader picks for their own app.

## Auth env var

The Tavily client reads `TAVILY_API_KEY` from the process env at construction
time. Missing-key handling is a deliberate UX choice:

- **Smoke test (no key required).** The smoke test injects a fake Tavily
  client into the agent module, so `uv run pytest tests/` works with no env
  configured. `tests/conftest.py` sets `ANTHROPIC_API_KEY=test-dummy` and
  `TAVILY_API_KEY=test-dummy` for the same reason (decoration-time
  validation in either layer never sees an empty string).
- **Runtime (key required).** The first call to `search_web(...)` with a
  missing or empty key raises a clear `TavilyConfigError` so the agent can
  fold the failure into a user-facing reply.
- **README** documents the env var and points at
  [tavily.com](https://tavily.com) for sign-up.

## Structure

The example lives under `examples/web-research/` at the repository root:

```
examples/web-research/
  README.md                       # voice matches examples/support-agent/README.md
  .env.example                    # ANTHROPIC_API_KEY + TAVILY_API_KEY
  pyproject.toml                  # depends on local ajolopy + httpx
  Dockerfile.prod                 # snapshot — `ajolopy deploy docker`
  .dockerignore                   # snapshot — `ajolopy deploy docker`
  fly.toml                        # snapshot — `ajolopy deploy fly`
  src/web_research/
    __init__.py                   # provider side-effect import
    main.py                       # async def app() — ajolopy dev entry point
    app_module.py                 # root @Module — wires Researcher
    tavily.py                     # thin httpx wrapper for Tavily search
    agents/
      __init__.py
      researcher.py               # @Agent + @Tool search_web + @Tool format_citations + @Stream
  data/
    sample-questions.jsonl        # 5 sample research prompts
  evals/
    researcher.jsonl              # 5 eval cases matching the metric shape
    researcher_eval.py            # @Eval(agent=Researcher) + 2 @Metrics
  tests/
    conftest.py                   # sets ANTHROPIC_API_KEY + TAVILY_API_KEY dummies + fake Tavily
    test_smoke.py                 # decorator/route/tool registration + fake-client format_citations roundtrip
```

The Tavily wrapper is **module-level injectable**: the agent's `search_web`
tool reads the client off a module-level singleton swap. The smoke test
overrides that singleton before exercising the agent module, exactly like
`dogfood/docsbot/agents/docs.py` does for its retriever. No DI / scope work
yet at the `@Stream` mount layer (the same trade-off the docs bot makes).

## Tools

- **`search_web(query: str, max_results: int = 5)`** — calls Tavily's
  `POST /search` endpoint and returns a list of
  `{"title": str, "url": str, "snippet": str}` dicts. The agent system
  prompt instructs the model to call this first for any time-sensitive or
  fact-grounded question.
- **`format_citations(answer: str, sources: list[dict[str, str]])`** —
  pure-Python helper that takes an answer string and a list of
  `{title, url}` source records and returns a Markdown footnoted version.
  Demonstrates **tool composition** (search → format) — the model can call
  it after `search_web` to produce a clean final answer.

Two tools intentionally — one I/O + one pure-Python — to make the
"composability" story tangible. Neither tool is async-only; `format_citations`
is sync since it has no I/O.

## Stream + wire shape

```python
class ResearchRequest(BaseModel):
    question: str

@Agent(
    model="claude-sonnet-4-7",
    system="You research and cite web sources. Always quote URLs.",
)
class Researcher:
    @Tool
    async def search_web(self, query: str, max_results: int = 5) -> list[dict[str, str]]: ...

    @Tool
    def format_citations(self, answer: str, sources: list[dict[str, str]]) -> str: ...

    @Stream("/chat")
    async def respond(self, body: Annotated[ResearchRequest, Body()]) -> AsyncGenerator[str]:
        async for chunk in self.stream(body.question):  # type: ignore[attr-defined]
            yield chunk
```

No `Memory` — research is stateless per request.

## Eval suite

```python
@Eval(
    agent=Researcher,
    dataset="evals/researcher.jsonl",
    threshold=0.8,
    concurrency=3,
)
class ResearcherEval:
    @Metric
    async def cites_sources(self, output, expected) -> float:
        """LLM-judge: does the answer cite concrete web sources?"""
        ...

    @Metric(aggregator="mean", pass_threshold=0.5)
    def contains_url(self, output, expected) -> float:
        """Deterministic: the answer contains at least one URL (http/https)."""
        ...
```

Five rows in `evals/researcher.jsonl`. Each row carries
`{"input": "<question>", "expected": {"topic": "<one-word>"}}`.

## Sample data

`data/sample-questions.jsonl` ships 5 research prompts that the README
walks through as a curl-able warm-up — distinct from the eval dataset, so
readers see both the "play with it" path and the "regression suite" path.

## Acceptance criteria

- [ ] `examples/web-research/` exists with the structure documented above.
- [ ] `examples/web-research/src/web_research/agents/researcher.py` defines a
      `Researcher` `@Agent` with `claude-sonnet-4-7`, a `search_web` `@Tool`,
      a `format_citations` `@Tool`, and a `@Stream("/chat")` handler bound
      to `Annotated[ResearchRequest, Body()]`.
- [ ] `examples/web-research/src/web_research/tavily.py` ships a thin
      `httpx.AsyncClient`-based wrapper for `POST /search` that reads
      `TAVILY_API_KEY` from the env. The wrapper exposes an async
      `search(query, max_results)` method returning
      `list[dict[str, str]]` (title/url/snippet keys), and raises a clear
      `TavilyConfigError` when the key is missing.
- [ ] The Tavily client is **swappable for tests**: the agents module looks
      up the active client via a module-level getter that `tests/conftest.py`
      overrides before the smoke test imports the agent.
- [ ] `examples/web-research/evals/researcher_eval.py` ships a
      `ResearcherEval` with one LLM-judge metric (`cites_sources`) and one
      deterministic metric (`contains_url`) that pass when the answer
      includes at least one `http(s)://...` URL.
- [ ] `examples/web-research/evals/researcher.jsonl` ships **at least five**
      sample rows in the dataset shape the metrics expect.
- [ ] `examples/web-research/data/sample-questions.jsonl` ships exactly
      five research prompts.
- [ ] `examples/web-research/pyproject.toml` declares `httpx` as a direct
      runtime dependency and uses `[tool.uv.sources]` to point `ajolopy` at
      the parent repo (`{ path = "../..", editable = true }`).
- [ ] `examples/web-research/.env.example` lists `ANTHROPIC_API_KEY` and
      `TAVILY_API_KEY` placeholders.
- [ ] `examples/web-research/README.md` walks step-by-step: install, env,
      `ajolopy dev`, three curl examples, `ajolopy eval --ci`, deploy via
      pre-generated `Dockerfile.prod` + `fly.toml`. Voice matches
      `examples/support-agent/README.md` and `dogfood/docsbot/README.md`.
- [ ] `examples/web-research/Dockerfile.prod`, `.dockerignore`, and
      `fly.toml` are present (snapshots of `ajolopy deploy docker` /
      `ajolopy deploy fly`).
- [ ] `examples/web-research/tests/conftest.py` sets dummy values for
      `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`, and registers a fake
      Tavily client into the agent module before the smoke test imports
      run. **No real HTTP calls are made by the tests.**
- [ ] `examples/web-research/tests/test_smoke.py` asserts decorator
      metadata for `Researcher`, the two `@Tool` markers, the
      `@Stream("/chat")` route, the `ResearchRequest` Pydantic model, the
      Tavily wrapper raises `TavilyConfigError` on a missing key, and the
      `format_citations` tool round-trips a fake search result into a
      Markdown-citation string.
- [ ] Repository root `README.md` gains an entry under `## Examples`
      pointing at `examples/web-research/`.
- [ ] `docs/next-steps.md` gains a bullet under "Read real projects"
      linking the absolute GitHub URL for `examples/web-research/`.
- [ ] `pyproject.toml` (root) registers `examples/web-research/` and
      `examples/web-research/tests/` in `tool.ruff.lint.per-file-ignores`
      coverage via the existing globs, and adds matching `pyright`
      `executionEnvironments` entries so `uv run pyright
      examples/web-research` passes.
- [ ] `uv run --group docs mkdocs build --strict` passes locally.
- [ ] `uv run ruff check examples/web-research` passes with zero violations.
- [ ] `uv run ruff format --check examples/web-research` passes.
- [ ] `uv run pyright examples/web-research` passes (strict typing).
- [ ] From inside the example directory:
      `cd examples/web-research && uv sync && uv run pytest tests/`
      passes (smoke test only, no network).

## Out of scope

- Alternative search providers (Bing / Google CSE / Brave / SerpAPI / etc.).
  Tavily-only for v0.1; readers who want a multi-provider abstraction can
  fork the example.
- Result caching (Redis / in-memory LRU on `search_web`). Adds complexity
  unrelated to the wedge lesson; deferred.
- Re-ranking or chunking of returned snippets. Tavily already returns
  scored snippets; for the v0.1 example we trust their ranking.
- Multi-turn research (follow-up questions on the same conversation).
  Stateless per request keeps the example focused on tool wiring.
- A real production rate-limit / retry / circuit-breaker. The example
  uses a single `httpx.AsyncClient` per request lifecycle; readers can
  add their own resilience layer.
- Translations. v0.1 example app is English-only.

## Implementation notes

- **HTTP-client injection seam.** Per the constraint that
  `@Stream` mounts the agent class with `cls()`, we cannot inject the
  Tavily client through a constructor. The pattern, copied from
  `dogfood/docsbot/agents/docs.py`, is a module-level getter:
  ```python
  _tavily_client: TavilyClient | None = None

  def get_tavily_client() -> TavilyClient:
      global _tavily_client
      if _tavily_client is None:
          _tavily_client = TavilyClient.from_env()
      return _tavily_client

  def set_tavily_client_for_tests(client: TavilyClient) -> None:
      """Test seam — overrides the process-wide singleton."""
      global _tavily_client
      _tavily_client = client
  ```
  The smoke test calls `set_tavily_client_for_tests(FakeTavilyClient(...))`
  in `conftest.py` before any agent code imports.
- **API drift** — same as the support-agent example: `@Agent` has no
  `trace=` kwarg; `@Stream` body is `Annotated[Model, Body()]`. The
  README notes this in passing where relevant.
- **Provider side-effect import.** `src/web_research/__init__.py` imports
  `ajolopy.providers.anthropic` so `@Agent(model="claude-...")` resolves
  at decoration time without `ProviderNotRegisteredError`.
- **Originality.** No code, prose, or structure copied from the external
  tutorials repo (Custom Non-Commercial License). Layout matches the
  Ajolopy in-repo examples (`examples/support-agent/`, `dogfood/docsbot/`).
- **`httpx` choice.** The framework already pins `httpx>=0.28.1` in the
  dev dep group. The example pins the same minimum so the wrapper has
  access to `httpx.AsyncClient.post(...)` with timeouts.
