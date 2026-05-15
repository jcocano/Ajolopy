# Ajolopy

> The Python framework for building AI-native applications in production.

[![PyPI](https://img.shields.io/pypi/v/ajolopy.svg)](https://pypi.org/project/ajolopy/)
[![Python](https://img.shields.io/pypi/pyversions/ajolopy.svg)](https://pypi.org/project/ajolopy/)
[![CI](https://github.com/jcocano/Ajolopy/actions/workflows/ci.yml/badge.svg)](https://github.com/jcocano/Ajolopy/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-mkdocs--material-blue.svg)](https://jcocano.github.io/Ajolopy/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**[Documentation](https://jcocano.github.io/Ajolopy/) · [Quickstart](https://jcocano.github.io/Ajolopy/quickstart/) · [Tutorial](https://jcocano.github.io/Ajolopy/tutorial/) · [Reference](https://jcocano.github.io/Ajolopy/reference/) · [Recipes](https://jcocano.github.io/Ajolopy/recipes/observability/)**

What Rails was for database-backed web apps and what NestJS is for
enterprise Node services: the default choice when what you're building
has **LLMs, agents, tools, prompts, evals, streaming, and MCP** as core
ingredients — not as an addon.

Ajolopy does not compete with FastAPI or LangChain. It competes for the
*complete AI-native application framework* category, which was empty in
Python before v0.1.

## Install

```bash
pip install ajolopy           # or: uv pip install ajolopy
```

Requires Python 3.14+. Optional extras documented under [Install](https://jcocano.github.io/Ajolopy/install/):
`otel`, `mcp`, `redis`, `postgres`, `mongo`, `qdrant`, `pgvector`.

## The killer demo

Twelve real lines (plus imports). Each token has a job — see the
[Step 1 tutorial](https://jcocano.github.io/Ajolopy/tutorial/step-1-hello/)
for the line-by-line breakdown.

```python
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body


class ChatRequest(BaseModel):
    message: str


@Agent(
    model="claude-sonnet-4-7",
    system="You are Acme Support. Be concise, friendly, and accurate.",
    fallback="claude-haiku-4-5",
)
class Support:
    @Tool
    async def lookup_order(self, order_id: str) -> dict[str, str]:
        """Look up an order's current state by id."""
        return {"order_id": order_id, "status": "in_transit", "eta": "tomorrow"}

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]):
        async for chunk in self.stream(body.message):
            yield chunk
```

Run it:

```bash
ajolopy new acme-support
cd acme-support
uv sync
ajolopy dev
```

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is order 4392? Use the tool."}'
```

Token-by-token streaming response, function-calling loop, env-var
validation at boot, fallback to `claude-haiku-4-5` on retriable
failure, OpenTelemetry spans for free. Twelve lines.

## Why Ajolopy

The framework targets the seven production pains the wedge AI Engineer
hits in week one:

1. **Env vars** — `ajolopy dev` refuses to boot with missing required
   variables. No more 2 a.m. discovery in staging.
2. **Cost** — every span carries `gen_ai.cost_usd`. Sum by user /
   tenant / agent in one SQL query against your trace backend.
3. **Evals as a CI gate** — `ajolopy eval --ci` blocks the PR when a
   metric regresses. The model upgrade that quietly broke safety is
   visible *before* a customer reports it.
4. **SSE streaming with backpressure** — `@Stream` handles disconnects,
   heartbeats, and cancellation. Not 30 lines of Starlette glue.
5. **Cross-provider fallback** — `fallback="claude-haiku-4-5"` cuts in
   when Anthropic returns a retriable error. Switching providers is a
   kwarg, not a rewrite.
6. **Diagnostics** — `ajolopy doctor` runs twelve health checks:
   Python version, env vars, deps, provider connectivity, etc.
   Lighthouse for AI apps.
7. **Project layout** — `ajolopy new` scaffolds a NestJS-style module
   tree. Any senior backend dev reads it on first sight.

[Read the long form](https://jcocano.github.io/Ajolopy/) for the full
framing.

## The 10 primitives

| AI (7)                                                                  | Framework (3)                          |
| ----------------------------------------------------------------------- | -------------------------------------- |
| `@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Metric`, `@Workflow`, `@MCP`   | `@Module`, `@Injectable`, `@Controller` |

Every primitive ships with a **magical default** (covers the 90% case
with zero ceremony) and an **escape hatch** (subclass or override) for
the 10% that needs full control. The surface is locked at ten — anything
that would require an eleventh decorator goes to v0.2+.

## What's in the box (v0.1)

- **Multi-provider LLM** — Anthropic, OpenAI, Gemini, and a universal
  OpenAI-compatible client that covers Ollama / Together / Groq /
  Mistral / DeepSeek / OpenRouter / Bedrock / Azure.
- **`ajolopy deploy <target>`** — generates `fly.toml`, `railway.json`,
  `render.yaml`, `vercel.json` (with warnings), or a universal
  `Dockerfile.prod` for k8s / VPS / ECS.
- **Memory** — five chat-history backends behind one `Memory` ABC:
  in-memory, Redis, Postgres, Mongo, SQLite.
- **RAG** — `Retriever` ABC with Qdrant and pgvector backends.
- **MCP** — `@MCP` to consume external Model Context Protocol servers,
  `@MCPServer` to publish your own `@Tool` methods as one.
- **Observability** — OpenTelemetry on by default; five recipes for
  [Langfuse, Sentry, Grafana, Honeycomb, and Datadog](https://jcocano.github.io/Ajolopy/recipes/observability/).
- **Eval framework** — `@Eval` + `@Metric` with built-in metrics
  (`exact_match`, `json_match`, `llm_judge`, `contains`,
  `intent_match`, `tool_called`) and regression detection.
- **CLI** — `new`, `dev`, `doctor`, `env:show/validate/diff`,
  `generate`, `eval`, `deploy`.

## Examples

- **[`examples/support-agent/`](./examples/support-agent/)** — runnable
  companion to the
  [3-step killer demo tutorial](https://jcocano.github.io/Ajolopy/tutorial/).
  Fork it, set `ANTHROPIC_API_KEY`, run `uv sync && ajolopy dev`, and
  watch every primitive from `@Agent` through `@Workflow` and `@MCP`
  answer real HTTP requests.
- **[`examples/web-research/`](./examples/web-research/)** — the
  canonical "wire an external HTTP API as a `@Tool`" reference. A
  `Researcher` agent that calls the [Tavily](https://tavily.com)
  search API through one `@Tool`, composes a Markdown-cited answer
  through a second pure-Python `@Tool`, and streams the result over
  SSE. Ships with `@Eval` + LLM-judge regression suite and pre-built
  `Dockerfile.prod` + `fly.toml`.
- **[`examples/oncall-agent/`](./examples/oncall-agent/)** — focused
  demo of the `@MCP` primitive against a real external server.
  Spawns the canonical
  [`@modelcontextprotocol/server-github`](https://github.com/modelcontextprotocol/servers/tree/main/src/github)
  over stdio so the on-call agent can search issues, PRs, and commits
  while triaging incidents. Pairs a local `@Tool` with the MCP tools
  to show how Ajolopy resolves name collisions in favour of local code.
- **[`examples/local-ollama/`](./examples/local-ollama/)** — the same
  `@Agent` + `@Tool` + `@Stream` shape running on a local
  [Ollama](https://ollama.com) server through Ajolopy's universal
  OpenAI-compatible provider. **No API key required** — install Ollama,
  `ollama pull llama3.3`, `uv sync && ajolopy dev`, and the streaming
  code reviewer answers `POST /chat` entirely on your laptop.
- **[`examples/memory-assistant/`](./examples/memory-assistant/)** —
  persistent task tracker showing `@Agent(memory="redis://...")`
  end-to-end. A `Memory` escape-hatch wrapper partitions chat history
  by a request-scoped `session_id`, so two users hitting the same
  `/chat` endpoint see independent transcripts in Redis. Ships with a
  `docker-compose.yml` (app + Redis) and a 5-row eval suite whose
  `memory_isolation` metric catches cross-session leaks.
- **[`dogfood/docsbot/`](./dogfood/docsbot/)** — Ajolopy's own docs bot,
  the first dogfood app. Answers questions about the framework using an
  in-memory `Retriever` subclass over the project's own `docs/` tree.
  Exercises `@Agent` + `@Tool` + `@Stream` + `@Eval` end-to-end and ships
  pre-generated `Dockerfile.prod` + `fly.toml` so it can be deployed in
  one `fly deploy`.
- **[`examples/contextual-rag/`](./examples/contextual-rag/)** —
  production-grade RAG agent with contextual chunking, hybrid
  retrieval, and citation-enforcing evals over a synthetic handbook.
  Builds on `dogfood/docsbot` with header-based chunks, a 0.4 keyword
  + 0.6 semantic-hash hybrid scorer, and three eval metrics (one
  LLM-as-judge, two deterministic) that fail when citations are
  missing or point at the wrong section. Documents the upgrade path to
  `QdrantRetriever` / `PgvectorRetriever` for real embeddings.

## Where to go next

- **[Quickstart](https://jcocano.github.io/Ajolopy/quickstart/)** —
  five minutes from `pip install` to a streaming agent.
- **[Tutorial](https://jcocano.github.io/Ajolopy/tutorial/)** — the
  three-step killer demo arc (hello → evals → multi-agent + MCP) in
  ~55 lines.
- **[Reference](https://jcocano.github.io/Ajolopy/reference/)** — one
  page per primitive with every kwarg and the escape hatch.
- **[Observability recipes](https://jcocano.github.io/Ajolopy/recipes/observability/)**
  — Langfuse / Sentry / Grafana / Honeycomb / Datadog wired in via
  the standard OTel exporter.

## Status

**v0.1 — first public release.** APIs are stable for the 10 primitives;
expect additive changes in v0.1.x. Pin exact versions if you depend on
the framework today.

The roadmap and current work are tracked in
[`board.json`](./board.json), validated against
[`.board-schema.json`](./.board-schema.json). Prose specs live in
[`specs/`](./specs).

## Contributing

Work is tracked on a PM-style board.
[`AGENTS.md`](./AGENTS.md) documents the claim / branch / transition
protocol for both human and AI contributors. The
[contributor release guide](https://jcocano.github.io/Ajolopy/contributing/release/)
covers how to cut a new version.

```bash
uv run python tools/board.py list      # see what's open
uv run python tools/board.py next      # see what to pick up next
```

File issues or open discussions at
[github.com/jcocano/Ajolopy](https://github.com/jcocano/Ajolopy).

## License

MIT — see [`LICENSE`](./LICENSE).

> The axolotl regenerates. So does Ajolopy.
