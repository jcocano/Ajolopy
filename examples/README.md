# Ajolopy examples

Six runnable apps, each one a focused demonstration of an
**Ajolopy primitive** mapped onto a **production scenario**. Every
example is checked into this repo, depends on `ajolopy` via a path
install (`[tool.uv.sources]`), and ships:

- a `README.md` walkthrough,
- a network-free `pytest` smoke suite,
- an `evals/` directory with at least one regression metric,
- pre-generated `Dockerfile.prod` + `.dockerignore` (and `fly.toml`
  for the cloud-deploy candidates).

Pick the example whose **production scenario** matches the problem
you're solving today. If a primitive shows up in more than one
example, the example whose `README.md` headlines it is the canonical
reference.

---

## [`support-agent/`](./support-agent/) — the killer-demo arc

The runnable companion to the
[3-step killer-demo tutorial](https://jcocano.github.io/Ajolopy/tutorial/):
one `@Agent` + one `@Tool` + one `@Stream` in Step 1, an `@Eval` gate
in Step 2, three specialists routed by a coordinator + `@MCP`
integrations in Step 3 — all in ~55 lines.

**Reach for this when:**

- Bootstrapping a brand-new agent in production and want the canonical
  shape (single agent → workflow → MCP) on disk to copy from.
- Onboarding a new contributor to the framework — the file layout is
  identical to what `ajolopy new` generates.

**Primitives exercised:** `@Agent`, `@Tool`, `@Stream`, `@Eval`,
`@Workflow`, `@MCP`, `@Module`.

---

## [`memory-assistant/`](./memory-assistant/) — multi-turn chat with Redis

A personal task tracker that demonstrates `@Agent(memory="redis://...")`
end-to-end. A `SessionScopedMemory` escape-hatch wrapper plus a
request-scoped `ContextVar` partition chat history per `session_id`,
so two users hitting the same `/chat` endpoint see independent
transcripts. Ships a `docker-compose.yml` with an app + healthchecked
Redis service.

**Reach for this when:**

- Building a chatbot / copilot / coding assistant — anything that
  needs to remember what the user said two turns ago.
- Onboarding a team to the Memory ABC and the per-user partitioning
  pattern. The `memory_isolation` eval metric catches cross-session
  leaks in CI.
- Picking a Memory backend: the same agent code points at Redis,
  Postgres, Mongo, SQLite, or in-memory by changing the URL scheme.

**Primitives exercised:** `@Agent` (memory kwarg), `@Tool`, `@Stream`,
`@Eval`, `@Metric`.

---

## [`contextual-rag/`](./contextual-rag/) — production-grade RAG with citations

An internal-knowledge-base assistant that demonstrates the three
quality bumps every serious RAG system needs:

1. **Contextual chunking** — each chunk carries surrounding context
   (parent section title, doc-level summary) so retrieved chunks make
   sense in isolation.
2. **Hybrid retrieval** — combines a keyword score (Jaccard over
   stopword-stripped tokens) with a semantic score (deterministic
   hash-similarity in v0.1; real embeddings via Qdrant / pgvector for
   production).
3. **Citations** — every answer cites the source path. A deterministic
   eval metric fails the PR when citations are missing.

**Reach for this when:**

- Building an "answer over our internal handbook / docs / wiki" app.
- Replacing a vanilla LangChain RAG with something opinionated about
  chunking + citation hygiene.
- Showcasing real RAG at a launch, internal demo, or sales meeting.

**Primitives exercised:** `@Agent`, `@Tool` (`retrieve_with_context`
+ `format_answer_with_citations`), `@Stream`, `@Eval`,
`@Metric`, `Retriever` ABC (subclassed).

---

## [`web-research/`](./web-research/) — external HTTP API as a `@Tool`

A research assistant that calls the
[Tavily](https://tavily.com) search API through one `@Tool`, folds the
results into a Markdown-cited answer through a second pure-Python
`@Tool`, and streams the result over SSE. Includes a clean
HTTP-client injection seam so the smoke suite runs network-free.

**Reach for this when:**

- Wiring a third-party REST API (search, weather, internal microservice,
  payment processor) into an agent as a `@Tool`. The Tavily wrapper is
  the canonical pattern.
- Building an "answer with citations" app where the citations come from
  the live web, not a frozen corpus.
- Demonstrating tool composition (search → format) plus testable
  external-API integration to a reviewer.

**Primitives exercised:** `@Agent`, `@Tool` (×2 — async HTTP + pure
Python), `@Stream`, `@Eval`, `@Metric`.

---

## [`oncall-agent/`](./oncall-agent/) — `@MCP` consuming a real external server

An on-call triage assistant that spawns the canonical
[`@modelcontextprotocol/server-github`](https://github.com/modelcontextprotocol/servers/tree/main/src/github)
over stdio so the model can search issues, PRs, and commits while
triaging incidents. Pairs a local `@Tool` with the MCP tools to
demonstrate the local-tool-wins-on-collision rule. Boots cleanly
without the `ajolopy[mcp]` extra or a `GITHUB_TOKEN` — the local
`@Tool` keeps answering when the MCP server is unhealthy.

**Reach for this when:**

- Building any internal agent that talks to GitHub, Linear, Jira,
  Slack, Linear, or any other system that publishes an MCP server.
  Drop in the published MCP server URL and you get every tool that
  server exposes, namespaced as `<server_key>__<tool>`.
- Demonstrating Ajolopy's MCP integration to a stakeholder — the
  framework is one of the few Python options that ships `@MCP` as a
  first-class decorator.
- Showcasing graceful degradation: when the MCP server is down, the
  agent keeps answering from its local tools.

**Primitives exercised:** `@Agent`, `@MCP`, `@Tool` (local +
MCP-injected), `@Stream`, `@Eval`.

---

## [`local-ollama/`](./local-ollama/) — privacy-first local LLM with cloud fallback

A code reviewer that runs on a local [Ollama](https://ollama.com)
server through Ajolopy's universal OpenAI-compatible provider.
**No API key required** to boot — install Ollama, pull a model, and
the agent answers `POST /chat` entirely on the user's machine. Wires
`fallback="claude-haiku-4-5"` to demonstrate cross-provider fallback
(production pain #5: "Anthropic outage = app caída"); thanks to
AJ-69's lazy fallback, the cloud provider only constructs when the
local Ollama primary fails.

**Reach for this when:**

- Building a privacy-first / on-prem / air-gapped agent that must not
  send tokens to a third party.
- Optimizing cost: serve cheap local inference for the 90% case, fall
  back to a paid model only when the local one falters.
- Pointing the universal provider at LM Studio, vLLM, or any other
  OpenAI-compatible local server — the `OLLAMA_BASE_URL` env var is
  enough (AJ-68).
- Demonstrating cross-provider resilience to a wary reviewer.

**Primitives exercised:** `@Agent` (universal provider + `fallback=`),
`@Tool` (stdlib-only `ast.parse`), `@Stream`, `@Eval`, `@Metric`.

---

## See also

- **[`../dogfood/docsbot/`](../dogfood/docsbot/)** — Ajolopy's own docs
  bot. Indexed over the `docs/` tree at build time; demonstrates the
  in-memory `Retriever` escape hatch for use cases where running a
  real vector DB is overkill. The first **dogfood app** (`AJ-54`) the
  framework ships against itself.
- **[Documentation](https://jcocano.github.io/Ajolopy/)** — Quickstart,
  Tutorial, per-primitive Reference, Observability recipes, Releasing
  to PyPI.
- **[Contributing](https://jcocano.github.io/Ajolopy/contributing/release/)**
  — board protocol, claim flow, release flow. Read
  [`AGENTS.md`](../AGENTS.md) before opening a PR.

---

## How to run an example

Each example is a stand-alone `uv` workspace that depends on the
parent `ajolopy` via path install. From the repo root:

```bash
cd examples/<name>
uv sync                       # install deps + the parent ajolopy editable
cp .env.example .env          # only the keys you actually need
ajolopy dev                   # streaming SSE server on http://127.0.0.1:8000
```

Network-free smoke tests:

```bash
uv run pytest tests/
```

Eval suite against a live provider (set the relevant API key first):

```bash
uv run ajolopy eval --ci
```

Build a production image:

```bash
docker build -f Dockerfile.prod -t <name>:latest .
```
