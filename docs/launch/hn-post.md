# Show HN draft

## Title

**Show HN: Ajolopy – Python framework for AI-native apps (decorators for agents, evals, MCP)**

(Alternative title to A/B test: `Ajolopy – NestJS for Python LLM apps`.)

## URL

`https://github.com/jcocano/Ajolopy`

## Body

Building an AI-native app in Python today means stitching together a
web framework, an LLM SDK, a streaming layer, a tool-call dispatcher,
an evaluation harness, prompt versioning, MCP transports,
observability, and a project layout convention. Each piece is fine in
isolation; the integration tax is what burns out the AI Engineer at a
Series-A startup.

Ajolopy ships all of that as one opinionated framework with ten
decorators. The goal is what Rails became for database-backed web
apps and what NestJS became for enterprise Node services: a default
choice, not a stack you assemble.

The killer demo is twelve lines:

```python
from typing import Annotated
from pydantic import BaseModel
from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body


class ChatRequest(BaseModel):
    message: str


@Agent(
    model="claude-sonnet-4-7",
    system="You are Acme Support.",
    fallback="claude-haiku-4-5",
)
class Support:
    @Tool
    async def lookup_order(self, order_id: str) -> dict[str, str]:
        return {"order_id": order_id, "status": "in_transit"}

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]):
        async for chunk in self.stream(body.message):
            yield chunk
```

That's an agent with a function-calling loop, cross-provider fallback,
SSE streaming with backpressure, env-var validation at boot, and one
OpenTelemetry span per call — all from the decorator surface. The
roughly equivalent ad-hoc stack is ~150 lines and four dependencies.

What's in v0.1:

- Ten primitives (`@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Metric`,
  `@Workflow`, `@MCP`, `@Module`, `@Injectable`, `@Controller`). The
  surface is locked at ten on purpose.
- Multi-provider: Anthropic, OpenAI, Gemini, and a universal
  OpenAI-compatible client (Ollama, Together, Groq, Mistral, DeepSeek,
  OpenRouter, Bedrock, Azure).
- Multi-deploy: `ajolopy deploy <target>` generates `fly.toml`,
  `railway.json`, `render.yaml`, `vercel.json`, or a universal
  `Dockerfile.prod`.
- Eval framework with CI gating (`ajolopy eval --ci` exits non-zero
  on metric regression).
- OpenTelemetry on by default, with five documented backend recipes
  (Langfuse, Sentry, Grafana, Honeycomb, Datadog).
- Memory ABC with five backends (in-memory, Redis, Postgres, Mongo,
  SQLite); RAG `Retriever` ABC with Qdrant and pgvector.
- MCP both ways: `@MCP` consumes servers, `@MCPServer` publishes your
  `@Tool`s.
- CLI: `new`, `dev`, `doctor`, `env:show/validate/diff`, `generate`,
  `eval`, `deploy`.

Docs and a runnable companion app:

- 5-minute Quickstart: <https://jcocano.github.io/Ajolopy/quickstart/>
- 3-step tutorial (hello → evals → multi-agent + MCP):
  <https://jcocano.github.io/Ajolopy/tutorial/>
- Reference for every primitive:
  <https://jcocano.github.io/Ajolopy/reference/>
- `examples/support-agent/` in the repo materialises every snippet
  from the tutorial as actual code.
- `dogfood/docsbot/` is Ajolopy's own docs bot — first dogfood app.

The framework targets Python 3.14+ and uses `uv` for project setup.
MIT licensed.

Happy to answer questions about the design choices — in particular
why the surface is locked at ten primitives, why Pyright (not mypy),
and why every target is pure (no platform-CLI shell-outs in v0.1).

## Talking points (for replies)

Reviewers will ask these — keep punchy responses ready:

- **"Why not LangChain / LlamaIndex / LangGraph?"** → those are AI
  *libraries*. Ajolopy is an *application framework*. Different
  category, complementary not competitive. You can use a LangChain
  retriever from inside an Ajolopy `@Tool` if that's what you want.
- **"Why not FastAPI / Starlette?"** → Ajolopy builds *on*
  Starlette under the hood. FastAPI doesn't ship `@Agent`,
  `@Workflow`, eval harness, MCP, prompt caching, fallback policy, or
  a deploy CLI. Different layer of the stack.
- **"Why the decorator soup?"** → Each decorator is one production
  pain. The Brief lists seven; the framework collapses them to one
  kwarg or one annotation each. Read the tutorial — the line-by-line
  table makes the trade explicit.
- **"Why locked at 10 primitives?"** → Because eleven becomes twenty
  becomes fifty becomes Spring. The surface stays small on purpose;
  extensions go through escape hatches (subclass, custom retriever,
  custom transport).
- **"Pre-alpha?"** → No. v0.1 is shipping. APIs are stable for the
  ten primitives. Pin versions if you build on top.
- **"Why Pyright and not mypy?"** → Anthropic's own SDK
  (`anthropic-sdk-python`, `claude-agent-sdk-python`) uses Pyright
  strict. Matching the upstream type-checker reduces friction for
  contributors and users.

## Post-launch chores

- Cross-link the HN URL on the docs site footer (`docs/index.md`).
- Pin the X thread on the project account.
- File a `release/v0.1.0-retrospective.md` issue 7 days post-launch
  with the metrics that mattered (npm-style: install count, GH stars,
  HN rank).
