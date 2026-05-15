# Reference

One page per primitive. Each page covers the public signature, a working
quick example, the kwargs table, the escape hatches, common gotchas, and
a link back to the corresponding spec for full detail.

Ajolopy ships **11 decorators** plus **one HTTP middleware** in v0.1. The
AI primitives sit at the top of the table; the framework primitives close
it. The split mirrors Brief v4.0: AI primitives express what the app
does; framework primitives compose how it runs.

## AI primitives (7 + MCP server)

| Decorator                                | Purpose                                                     | When to use                                                              |
|------------------------------------------|-------------------------------------------------------------|--------------------------------------------------------------------------|
| [`@Agent`](agent.md)                     | Turn a class into an LLM-powered agent.                     | One agent, one LLM, optional tools / memory / fallback / tracing.        |
| [`@Tool`](tool.md)                       | Expose a method to the LLM as a callable tool.              | Add a capability to an `@Agent` — function-calling loop runs for free.   |
| [`@Stream`](stream.md)                   | Bind an async generator to an SSE HTTP endpoint.            | Stream tokens / events from an agent or workflow over HTTP.              |
| [`@Workflow`](workflow.md)               | Multi-agent orchestration with a coordinator or `route()`.  | Two or more agents that hand off, with optional LLM-driven routing.      |
| [`@MCP`](mcp.md)                         | Consume external MCP servers as tools.                      | Inject GitHub / Linear / Stripe MCP tools into an agent or workflow.     |
| [`@MCPServer`](mcp-server.md)            | Publish `@Tool` methods over stdio / HTTP / SSE.            | Expose your tools to Claude Desktop or other MCP clients.                |
| [`@Eval` + `@Metric`](eval.md)           | Evaluation suite + per-metric aggregation.                  | Regression-detect an agent / workflow against a JSONL dataset.           |

## Framework primitives (3 + 1 middleware)

| Decorator                                | Purpose                                                     | When to use                                                              |
|------------------------------------------|-------------------------------------------------------------|--------------------------------------------------------------------------|
| [`@Module`](module.md)                   | Group providers / controllers / agents into a DI module.    | Compose the app's dependency graph at the class level.                   |
| [`@Injectable`](injectable.md)           | Mark a class as a DI provider with a scope.                 | Declare services that other classes depend on.                           |
| [`@Controller`](controller.md)           | Bind HTTP routes to a class with a path prefix.             | Non-streaming HTTP endpoints (`@Get`, `@Post`, ...).                     |
| [`@UseGuards`](use-guards.md)            | Gate routes behind one or more `Guard` instances.           | Bearer-token auth, IP allowlisting, or any custom request-level check.   |

## Reading order

If you are new to Ajolopy, the recommended walk through the reference is:

1. [`@Agent`](agent.md) — the single most important primitive.
2. [`@Tool`](tool.md) — capabilities, one line each.
3. [`@Stream`](stream.md) — HTTP delivery, one decorator.
4. [`@Workflow`](workflow.md) — when one agent stops being enough.
5. [`@MCP`](mcp.md) / [`@MCPServer`](mcp-server.md) — interoperate with
   external tool ecosystems.
6. [`@Eval`](eval.md) — measure before you regress.
7. [`@Module`](module.md) / [`@Injectable`](injectable.md) /
   [`@Controller`](controller.md) — wire everything together once the
   app outgrows a single file.
8. [`@UseGuards`](use-guards.md) — gate the surface before shipping.

## Design contract

Every primitive on these pages follows the framework-wide
**"magical default + escape hatch"** rule:

- A **default mágico** (typically a string of config) covers ~90% of cases
  with zero ceremony.
- An **escape hatch** (subclass a base class, override a method, pass a
  callable instead of a string) gives full control to the ~10% case.

Each page calls out both halves under "Quick example" and
"Escape hatches".
