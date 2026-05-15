# Ajolopy

> The Python framework for building AI-native applications in production.

**[Documentation](https://jcocano.github.io/Ajolopy/) · [Quickstart](https://jcocano.github.io/Ajolopy/quickstart/) · [Install](https://jcocano.github.io/Ajolopy/install/)**

What Rails was for database-backed web apps and what NestJS is for enterprise Node services: the default choice when what you're building has **LLMs, agents, tools, prompts, evals, streaming, and MCP** as core ingredients — not as an addon.

It doesn't compete with FastAPI or LangChain. It competes for the *complete AI-native application framework* category, which is currently empty in Python.

> The axolotl regenerates. So does Ajolopy.

---

## Status

**Pre-alpha — active development.** The development harness is in place; the first primitive (`@Agent`) is next. v0.1 roadmap: the 10 core primitives at 20 hrs/week ≈ 10–16 months.

## The 10 primitives

| AI (7) | Framework (3) |
|---|---|
| `@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Metric`, `@Workflow`, `@MCP` | `@Module`, `@Injectable`, `@Controller` |

Every primitive ships with a **magical default** (covers the 90% case with zero ceremony) and an **escape hatch** (subclass / override for the 10% that needs full control).

## Development setup

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.14+.

```bash
git clone https://github.com/jcocano/ajolopy.git
cd ajolopy
uv sync
uv run pre-commit install
uv run pytest
```

## Contributing

Work is tracked on a PM-style board in [`board.json`](./board.json), validated
against [`.board-schema.json`](./.board-schema.json). Prose specs live in
[`specs/`](./specs). Read [`AGENTS.md`](./AGENTS.md) before claiming an
item — it documents the CLI, the workflow, and the conventions for both human
and AI contributors.

```bash
uv run python tools/board.py list      # see what's open
uv run python tools/board.py next      # see what to pick up next
```

## License

MIT — see [`LICENSE`](./LICENSE).
