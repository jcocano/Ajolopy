# Next steps

You finished the [Quickstart](quickstart.md) and have a streaming agent
running locally. Here is where to go from here.

## Learn the primitives in depth

- **[Tutorial — the three-step killer demo arc](tutorial/index.md).** A
  guided build of a non-trivial agent that exercises `@Agent` + `@Tool` +
  `@Stream` + `@Eval` + `@Workflow` + `@MCP` end to end. Read it in order:
    - [Step 1 — Hello to prod](tutorial/step-1-hello.md)
    - [Step 2 — Evals](tutorial/step-2-evals.md)
    - [Step 3 — Equipo](tutorial/step-3-team.md)
- **[Reference — per-primitive documentation](reference/index.md).** One
  page per primitive with the full signature, every option, the
  default-magical form, and the escape-hatch subclass pattern.

## Read real projects

- **[`examples/support-agent`](https://github.com/jcocano/Ajolopy/tree/main/examples/support-agent)**
  is the runnable companion to the
  [3-step killer demo tutorial](tutorial/index.md). Fork it, set
  `ANTHROPIC_API_KEY`, and run `uv sync && ajolopy dev` to see every
  primitive in action against a real provider.
- **[`examples/web-research`](https://github.com/jcocano/Ajolopy/tree/main/examples/web-research)**
  is the canonical "wire an external HTTP API as a `@Tool`" reference
  ([`AJ-65`](https://github.com/jcocano/Ajolopy/blob/main/board.json)).
  A `Researcher` agent that calls the [Tavily](https://tavily.com)
  search API through one `@Tool` and folds the results into a
  Markdown-cited answer through a second pure-Python `@Tool`. Ships
  with an `@Eval` regression suite plus pre-built `Dockerfile.prod` +
  `fly.toml`.
- **[`examples/oncall-agent`](https://github.com/jcocano/Ajolopy/tree/main/examples/oncall-agent)**
  is the focused [`@MCP`](reference/mcp.md) demo
  ([`AJ-63`](https://github.com/jcocano/Ajolopy/blob/main/board.json)).
  Wires the canonical GitHub MCP server into a small on-call agent so
  the model can search issues / PRs / commits while triaging
  incidents. Boots cleanly without a `GITHUB_TOKEN` — the agent's
  local `@Tool` keeps answering when the MCP server is unhealthy.
- **[`examples/local-ollama`](https://github.com/jcocano/Ajolopy/tree/main/examples/local-ollama)**
  is the **no-API-key** runnable example
  ([`AJ-66`](https://github.com/jcocano/Ajolopy/blob/main/board.json)).
  It runs `@Agent` + `@Tool` + `@Stream` against a local
  [Ollama](https://ollama.com) server through Ajolopy's universal
  OpenAI-compatible provider — install Ollama,
  `ollama pull llama3.3`, `uv sync && ajolopy dev`, and the streaming
  code reviewer answers `POST /chat` entirely on your laptop.
- **[`examples/memory-assistant`](https://github.com/jcocano/Ajolopy/tree/main/examples/memory-assistant)**
  is the persistent-assistant reference for
  `@Agent(memory="redis://...")`. A `SessionScopedMemory` wrapper plus a
  request `ContextVar` partition chat history per `session_id`, so two
  users hitting the same `/chat` endpoint see independent transcripts in
  Redis. Ships with a `docker-compose.yml`, a `Dockerfile.prod`, and a
  5-row eval suite whose `memory_isolation` metric catches cross-session
  leaks.
- **[`dogfood/docsbot`](https://github.com/jcocano/Ajolopy/tree/main/dogfood/docsbot)**
  is Ajolopy's own docs bot — the first dogfood app
  ([`AJ-54`](https://github.com/jcocano/Ajolopy/blob/main/board.json)).
  Answers questions about the framework using an in-memory `Retriever`
  subclass over the project's own `docs/` tree, exercises
  `@Agent` + `@Tool` + `@Stream` + `@Eval` end-to-end, and ships
  pre-generated `Dockerfile.prod` + `fly.toml`.
- **[`examples/contextual-rag`](https://github.com/jcocano/Ajolopy/tree/main/examples/contextual-rag)**
  is the RAG flagship example
  ([`AJ-67`](https://github.com/jcocano/Ajolopy/blob/main/board.json)).
  Contextual chunking (every chunk ships the parent section's
  summary), hybrid retrieval (0.4 keyword + 0.6 semantic-hash), and
  citation-enforcing evals (`addresses_query` LLM-judge plus two
  deterministic checks for the `[path#section]` citation block and
  the right cited section). Documents the upgrade path to
  `QdrantRetriever` / `PgvectorRetriever` for real embeddings.
- **Dogfood apps roadmap.** A small set of end-to-end Ajolopy projects
  maintained alongside the framework — the same way NestJS ships
  `nest-cli` examples. Tracked as
  [`AJ-54`](https://github.com/jcocano/Ajolopy/blob/main/board.json) and
  [`AJ-55`](https://github.com/jcocano/Ajolopy/blob/main/board.json).

## Put it in production

- **[Observability recipes](recipes/observability/index.md).** Five
  cookbooks plugged in via the `otel` extra:
  [Langfuse](recipes/observability/langfuse.md) ·
  [Sentry](recipes/observability/sentry.md) ·
  [Grafana stack](recipes/observability/grafana.md) ·
  [Honeycomb](recipes/observability/honeycomb.md) ·
  [Datadog](recipes/observability/datadog.md). Same pipeline, different
  exporter — pick one and you have traces + cost dashboards in under 10
  minutes.
- **Deploy templates.** Fly.io, Railway, Render, Vercel, and a
  universal Dockerfile — all generated by `ajolopy new` when you opt
  in.

## Contribute

Ajolopy is built in the open and tracks every piece of work on a
PM-style board in the repo.

- **[`board.json`](https://github.com/jcocano/Ajolopy/blob/main/board.json)**
  is the single source of truth for what is `ready`, `in_progress`,
  `blocked`, `in_review`, or `done`.
- **[`AGENTS.md`](https://github.com/jcocano/Ajolopy/blob/main/AGENTS.md)**
  documents the claim / branch / transition protocol for both human
  and AI contributors.
- **[`specs/`](https://github.com/jcocano/Ajolopy/tree/main/specs)**
  holds the prose spec for every board item — the design contract you
  build against.

```bash
uv run python tools/board.py list      # see what is open
uv run python tools/board.py next      # see what to pick up next
```

File issues or open discussions at
[github.com/jcocano/Ajolopy](https://github.com/jcocano/Ajolopy).

## Help and feedback

- **Issues & feature requests:**
  [github.com/jcocano/Ajolopy/issues](https://github.com/jcocano/Ajolopy/issues)
- **Security disclosures:** see
  [`SECURITY.md`](https://github.com/jcocano/Ajolopy/blob/main/SECURITY.md).
