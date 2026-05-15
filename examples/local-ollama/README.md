# `local-ollama` — Ajolopy with no API key, on your laptop

This is the **lowest-friction runnable example** of
[Ajolopy](../../README.md), tracked as
[`AJ-66`](../../specs/example-local-ollama.md). It demonstrates every
piece of the killer demo — `@Agent`, `@Tool`, `@Stream`, `@Eval` — but
**without ever leaving your machine and without ever asking for an API
key**. The model runs on a local [Ollama](https://ollama.com) server
through Ajolopy's universal OpenAI-compatible provider.

After the steps below a reader has a streaming code reviewer agent
listening on `POST /chat`, a `lint_function` tool that runs `ast.parse`
over the submitted snippet, and an eval suite scored by the same local
model. No accounts, no key paste, no quotas.

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- [Ollama](https://ollama.com/download) installed and running on
  `http://localhost:11434` (the default).

This example is checked into the Ajolopy repository so you do not need
a published `ajolopy` release: `pyproject.toml` points the dependency
at `../..` via `[tool.uv.sources]`.

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/local-ollama
uv sync
cp .env.example .env
# nothing to edit — there is no API key field
```

---

## Pull a model

The agent's `model` string is `"ollama:llama3.3"`. Pull the matching
weights with the Ollama CLI before the first run:

```bash
ollama pull llama3.3
```

A different model? Update the `model` kwarg in
`src/local_ollama/agents/reviewer.py` to match — anything Ollama can
serve (`llama3.2`, `mistral`, `qwen2.5-coder`, `phi3`) works as long as
the prefix stays `ollama:`. The framework's registry routes every
`ollama:*` string to the universal OpenAI-compatible provider.

---

## Run the reviewer

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      local_ollama.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal, hand the agent a Python snippet:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"code": "import os\n\ndef add(a, b):\n    return a + b\n"}'
```

The response streams back token by token. The agent:

- **`@Agent`** is wired to `ollama:llama3.3`. Decoration-time
  validation passes because the universal provider's `ollama` prefix
  does not require an API key. At request time, the framework opens a
  cached `AsyncOpenAI` client pointed at `http://localhost:11434/v1`.
- **`@Tool` `lint_function`** runs `ast.parse(code)` and reports
  `{"ok": True, "error": ""}` for clean code or
  `{"ok": False, "error": "<message>"}` for a syntax error. The agent's
  system prompt instructs the model to call it first on every request.
- **`@Stream("/chat")`** mounts the method as an SSE endpoint with
  heartbeats and disconnect cancellation.

Try a deliberately broken snippet:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"code": "def greet(name):\n    return f\"Hi, {name}\n"}'
```

The `lint_function` tool flags the unterminated f-string before the
model spends tokens reviewing further.

---

## Cross-provider fallback (no API key required for the happy path)

`CodeReviewer` declares two model entries — a **local primary** and a
**cloud fallback**:

```python
@Agent(
    model="ollama:llama3.3",
    fallback="claude-haiku-4-5",
    ...
)
class CodeReviewer:
    ...
```

The pattern is the framework's answer to **production pain #5** from the
Brief: "Anthropic outage = app caída". One declaration, two providers,
zero retry loop to write by hand.

Thanks to **AJ-69 (lazy fallback provider instantiation)** the cloud
fallback's provider is **not** constructed at decoration time. That means:

- Run the example with no `ANTHROPIC_API_KEY` and the local Ollama
  primary handles every request. The fallback never instantiates, so
  the Anthropic env var is never validated.
- Set `ANTHROPIC_API_KEY` in production and the fallback fires the
  first time the local primary returns a retriable error (timeout,
  connection refused, daemon down). The framework swaps to
  `claude-haiku-4-5` mid-request, logs a
  `gen_ai.fallback.used` attribute on the span, and the user sees an
  answer instead of a stack trace.

The `.env.example` ships `ANTHROPIC_API_KEY=` as an optional, empty
placeholder. Leave it empty for local development; set it before you
deploy.

---

## Why no API key?

The universal OpenAI-compatible provider routes by **prefix**. Every
prefix Ajolopy knows about ships with a per-prefix default base URL and
an opt-in API-key env var:

| Prefix       | Default base URL                          | API-key env var      |
|--------------|-------------------------------------------|----------------------|
| `ollama:`    | `http://localhost:11434/v1`               | _none_               |
| `groq:`      | `https://api.groq.com/openai/v1`          | `GROQ_API_KEY`       |
| `together:`  | `https://api.together.xyz/v1`             | `TOGETHER_API_KEY`   |
| `mistral:`   | `https://api.mistral.ai/v1`               | `MISTRAL_API_KEY`    |
| `deepseek:`  | `https://api.deepseek.com/v1`             | `DEEPSEEK_API_KEY`   |
| `openrouter:`| `https://openrouter.ai/api/v1`            | `OPENROUTER_API_KEY` |

Ollama runs locally and accepts any non-empty placeholder for the key,
so Ajolopy passes the literal string `"ollama"` to the SDK. The
framework reads no environment variable for the `ollama:` prefix.

### Remote Ollama (the escape hatch)

If you run Ollama on a different machine — a workstation with a GPU, a
homelab box, a remote VPS — construct
:class:`~ajolopy.providers.universal_openai.UniversalOpenAIProvider`
with the `base_urls=` kwarg and register it manually:

```python
import openai

from ajolopy.providers.universal_openai import UniversalOpenAIProvider
from ajolopy.providers.registry import register_provider

register_provider(
    "universal-openai",
    UniversalOpenAIProvider,
    overwrite=True,
)
# Or pass a pre-built AsyncOpenAI client per prefix:
provider = UniversalOpenAIProvider(
    base_urls={"ollama": "http://my-ollama.lan:11434/v1"},
    # clients={"ollama": openai.AsyncOpenAI(base_url="...", api_key="ollama")},
)
```

The `.env.example` documents `OLLAMA_BASE_URL` as a convention; the
framework itself does NOT read it.

---

## Run the eval suite

`evals/reviewer_eval.py` ships `ReviewerEval` over the five rows in
`evals/reviewer.jsonl` (one per seeded issue: unused import, missing
return type, off-by-one, mutable default arg, syntax error). Two
metrics, both running on the same local model:

- **`identifies_issue`** — LLM-as-judge over the agent's answer.
  Penalises generic responses, refusals to call `lint_function`, and
  answers that miss the seeded issue.
- **`response_within_budget`** — deterministic. Passes when the response
  is non-empty and shorter than 500 words.

Run it:

```bash
uv run ajolopy eval --ci
```

The CI form persists each run under `.ajolopy/eval-runs/` and compares
the next run against the previous baseline — the same regression
detection from
[`docs/tutorial/step-2-evals.md`](../../docs/tutorial/step-2-evals.md).

Heads-up: the eval suite is the only path in this example that actually
hits the Ollama server. It pulls the model just like the agent does, so
make sure `ollama serve` is running and `ollama pull llama3.3` has
completed first.

---

## Smoke test

The example ships a single, fast, network-free `pytest`:

```bash
uv run pytest tests/
```

It asserts the decorators land, the `lint_function` tool's two branches
return the expected shape, and the `@Stream("/chat")` metadata is in
place. No provider is called.

---

## Deploy (with a caveat)

`Dockerfile.prod`, `.dockerignore`, and `fly.toml` are pre-generated
snapshots of `ajolopy deploy docker` / `ajolopy deploy fly`. They build
and run the Python service the same way every other Ajolopy example
does — that part is straightforward:

```bash
docker build -f Dockerfile.prod -t local-ollama:latest .
docker run -p 3000:3000 --env-file .env local-ollama:latest
```

> **Deploying Ollama itself is non-trivial.** The Python service in
> this example is happy to run anywhere, but Ollama needs to live
> somewhere reachable from inside the container. Three production
> paths:
>
> 1. **Run your own Ollama on a long-lived host** (a workstation with
>    a GPU, an on-prem box, a VPS) and point the universal provider
>    at it with `base_urls={"ollama": "https://my-ollama.example/v1"}`
>    via the constructor escape hatch above.
> 2. **Swap `ollama:llama3.3` for a hosted OpenAI-compatible
>    prefix** the framework already routes —
>    `groq:llama-3.3-70b-versatile`,
>    `together:meta-llama/Llama-3.3-70B-Instruct-Turbo`, etc. — and
>    set that provider's API key in `.env`.
> 3. **Swap to a cloud provider entirely** (`claude-sonnet-4-7`,
>    `gpt-4o`, `gemini-1.5-pro`). Ajolopy's multi-provider design
>    means swapping is a one-line change to the `model` kwarg.

See [`docs/reference/cli-deploy.md`](../../docs/reference/cli-deploy.md)
for the full catalogue of `ajolopy deploy` targets.

---

## Layout

```
local-ollama/
  README.md                       ← you are here
  .env.example                    no API keys — just the optional OLLAMA_BASE_URL
  pyproject.toml                  depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                 snapshot — `ajolopy deploy docker`
  .dockerignore                   snapshot — `ajolopy deploy docker`
  fly.toml                        snapshot — `ajolopy deploy fly` (see deploy caveat)
  data/
    code-samples.jsonl            5 Python snippets with seeded issues
  src/local_ollama/
    __init__.py                   side-effect import for the universal provider
    main.py                       async def app() — ajolopy dev entry point
    app_module.py                 root @Module — wires CodeReviewer
    agents/
      __init__.py
      reviewer.py                 CodeReviewer — @Agent + @Tool + @Stream
  evals/
    reviewer.jsonl                sample rows for ReviewerEval
    reviewer_eval.py              @Eval(agent=CodeReviewer) + 2 @Metrics
  tests/
    conftest.py                   placeholder — no env vars required
    test_smoke.py                 decorator + tool + stream metadata; no provider calls
```

---

## Where to go next

- The [`examples/support-agent/`](../support-agent/) — the same shape
  against Anthropic. `git diff` against this directory to see what
  changes when swapping providers: one model string, one side-effect
  import, one env var.
- The [reference docs](https://jcocano.github.io/Ajolopy/reference/) —
  one page per primitive with every kwarg and the escape hatch.
- The [Ajolopy repository root README](../../README.md) for
  contributing and the project's design contract.
