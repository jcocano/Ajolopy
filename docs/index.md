# Ajolopy

> The Python framework for building **AI-native applications in production**.

What Rails was for database-backed web apps and what NestJS is for enterprise
Node services: the default choice when what you're building has **LLMs,
agents, tools, prompts, evals, streaming, and MCP** as core ingredients — not
as an addon.

Ajolopy does not compete with FastAPI or LangChain. It competes for the
*complete AI-native application framework* category, which is currently empty
in Python.

!!! note "Status: pre-alpha"
    The development harness is in place; the first primitives are landing
    under [`board.json`](https://github.com/jcocano/Ajolopy/blob/main/board.json).
    APIs are not stable yet — pin exact versions if you depend on the
    framework today.

---

## Why Ajolopy

Building an AI-native app today means stitching together:

- a web framework (FastAPI),
- an LLM SDK (Anthropic / OpenAI / Gemini),
- a streaming layer,
- a tool-call dispatcher,
- an evaluation harness,
- prompt versioning,
- MCP client and server transports,
- observability (OpenTelemetry, Langfuse, etc.),
- a project layout convention.

Ajolopy ships all of that as **one opinionated framework** with ten primitives.

## The 10 primitives

| AI (7) | Framework (3) |
| --- | --- |
| `@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Metric`, `@Workflow`, `@MCP` | `@Module`, `@Injectable`, `@Controller` |

Every primitive ships with a **magical default** that covers the 90% case
with zero ceremony, and an **escape hatch** (subclass or override) for the
10% that needs full control.

## Where to go next

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quickstart](quickstart.md)**
  Five minutes from `uv pip install ajolopy` to a working agent answering
  `curl` requests.

- :material-school: **[Tutorial](tutorial/index.md)**
  The three-step killer demo arc — agent, evals, multi-agent + MCP —
  in roughly 55 lines.

- :material-chart-line: **[Recipes](recipes/observability/index.md)**
  Plug Ajolopy into Langfuse, Sentry, Grafana, Honeycomb, or Datadog in
  under 10 minutes — same pipeline, different exporter.

- :material-package-variant: **[Install](install.md)**
  Core install plus the full optional-extras matrix (observability, MCP,
  memory backends).

- :material-map-marker-path: **[Next steps](next-steps.md)**
  Per-primitive reference, example projects, observability and deploy
  recipes, and how to contribute.

</div>

## Design tenets

- **Default magical, escape hatch always available.** Every primitive
  works as a one-line decorator and lets you subclass when you need full
  control.
- **No 11th primitive in v0.1.** Anything that would require a new
  decorator goes to v0.2+. The surface stays small on purpose.
- **Production from day one.** Observability, env validation, deploy
  templates, and evals are first-class — not addons.

## License

MIT. Source on [GitHub](https://github.com/jcocano/Ajolopy).
