# Install

## Requirements

- **Python 3.14+** (the framework relies on PEP 649 deferred-annotation
  evaluation, so older runtimes are not supported).
- [`uv`](https://docs.astral.sh/uv/) is the recommended package manager
  for both installing Ajolopy and creating new projects. The instructions
  below assume `uv`, but `pip` works identically.

## Core install

First, create and activate a Python 3.14 virtual environment so `uv pip
install` has a target to write into:

```bash
uv venv --python 3.14 .venv
source .venv/bin/activate
```

Then install the framework:

```bash
uv pip install ajolopy
```

!!! note "Why `--python 3.14`"
    Ajolopy requires Python 3.14+ (it relies on PEP 649 deferred
    annotations). Pinning the interpreter at `uv venv` time avoids
    picking up an older default on your machine.

This pulls a focused dependency set: the multi-provider LLM core
(`anthropic`, `openai`, `google-genai`), the ASGI runtime (`starlette`,
`uvicorn`), `pydantic` for typed config, and `structlog` for logging.

That is enough to run `@Agent`, `@Tool`, `@Stream`, `@Workflow`,
`@Module`, `@Injectable`, and `@Controller` against any of the four
built-in provider families (Anthropic / OpenAI / Gemini /
OpenAI-compatible).

## Optional extras

Everything else is **opt-in**. The framework still imports and
validates without the extra installed — it raises a typed error with a
`pip install` hint only when you actually try to *use* a feature that
depends on the missing SDK.

| Extra | Install | What it enables |
| --- | --- | --- |
| `otel` | `uv pip install "ajolopy[otel]"` | OpenTelemetry SDK + OTLP/HTTP exporter — turns the no-op spans into real exports to Langfuse / Honeycomb / Grafana Tempo / Datadog / Sentry. |
| `mcp` | `uv pip install "ajolopy[mcp]"` | The official Model Context Protocol SDK so `@MCP(...)` and `StdioMCPClient` / `HTTPMCPClient` / `SSEMCPClient` can actually connect. |
| `redis` | `uv pip install "ajolopy[redis]"` | `RedisMemory` backend for short-term conversation state. |
| `postgres` | `uv pip install "ajolopy[postgres]"` | `PostgresMemory` backend (via `asyncpg`) for durable, queryable memory. |
| `mongo` | `uv pip install "ajolopy[mongo]"` | `MongoDBMemory` backend (via `motor`) for document-shaped memory. |
| `memory-all` | `uv pip install "ajolopy[memory-all]"` | Convenience meta-extra: pulls every memory backend SDK at once. |

!!! note "Pinning extras"
    Extras compose. Install several at the same time:

    ```bash
    uv pip install "ajolopy[otel,mcp,redis]"
    ```

!!! warning "`pgvector` and `qdrant`"
    The Brief lists `pgvector` and `qdrant` as v0.1 database targets via
    the `ajolopy new` wizard. They surface as project-level
    dependencies in the generated `pyproject.toml`, not as Ajolopy
    extras — pick them in the wizard rather than installing them into
    the framework itself.

## Verifying the install

If you are in a fresh shell (no `.venv` yet), create and activate one
first so `uv pip install` has a target to write into:

```bash
uv venv --python 3.14 .venv
source .venv/bin/activate
```

Then install and import the framework:

```bash
uv pip install ajolopy
python -c "import ajolopy; print(ajolopy.__version__)"
```

If you see a version string, you are ready for the
[Quickstart](quickstart.md).

## Project-local install (recommended)

For real projects, prefer `uv add` inside an Ajolopy project:

```bash
ajolopy new my-agent
cd my-agent
uv add "ajolopy[otel,mcp]"
uv sync
```

This pins Ajolopy in `pyproject.toml` and the lockfile so every
contributor and every CI run sees the same versions.
