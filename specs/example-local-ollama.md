# AJ-66 — Example: local LLM agent (Ollama via universal provider, no API key)

> Status: backlog → ready · Type: docs · Priority: p1 · Milestone: v0.1
> Blocks: — (none) · Blocked by: — (none).

## Goal

Ship the **lowest barrier-to-entry runnable example** of the framework: a
streaming code reviewer that runs **entirely on the user's machine**
against a local [Ollama](https://ollama.com) server, with **zero cloud API
keys required**. After this lands, a reader can:

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/local-ollama
uv sync
ollama pull llama3.3
ajolopy dev
```

…and `POST /chat` with a chunk of Python and get a streamed, grounded
code review — no signup, no key paste, no leaving the laptop.

This is the third runnable example after
[`examples/support-agent/`](./docs-example-support.md) (AJ-50) and the
dogfood [`dogfood/docsbot/`](./dogfood-docsbot.md) (AJ-54). The strategic
angle is **multi-provider story under five minutes**: it proves the
framework's universal OpenAI-compatible provider works for Ollama with the
exact same `@Agent` + `@Tool` + `@Stream` surface a reviewer already saw
in the killer demo — only the model string changes.

## Why this matters

- **No-API-key onboarding.** Removes the single biggest friction point
  on the launch path: reviewers who want to try Ajolopy before
  committing to an Anthropic / OpenAI account can now do so end-to-end.
- **Multi-provider proof.** Hits the v0.1 non-negotiable "OpenAI-compatible
  universal provider that covers Ollama / Together / Groq / Mistral /
  DeepSeek / OpenRouter" with a runnable artifact, not a paragraph.
- **Privacy story.** The first Ajolopy demo where code and prompts never
  leave the laptop. Useful in regulated / on-prem-curious conversations
  the wedge AI Engineer keeps running into.
- **Single-file diff against AJ-50.** A reader can `git diff` against
  `examples/support-agent/` and see exactly what changes when swapping
  providers — one model string, one env var.

## Structure

The example lives under `examples/local-ollama/` at the repository root,
next to `examples/support-agent/`:

```
examples/local-ollama/
  README.md                       # walkthrough — install Ollama → pull → run → curl
  .env.example                    # only the Ollama URL (no API keys)
  pyproject.toml                  # depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                 # snapshot — `uv run ajolopy deploy docker`
  .dockerignore                   # snapshot — `uv run ajolopy deploy docker`
  fly.toml                        # snapshot — `uv run ajolopy deploy fly` (caveats apply)
  data/
    code-samples.jsonl            # 5 Python snippets with seeded issues
  src/local_ollama/
    __init__.py                   # side-effect import for the universal provider
    main.py                       # async def app() — ajolopy dev entry point
    app_module.py                 # root @Module — wires the Reviewer agent
    agents/
      __init__.py
      reviewer.py                 # CodeReviewer — @Agent + @Tool lint_function + @Stream
  evals/
    reviewer.jsonl                # ≥5 rows for ReviewerEval
    reviewer_eval.py              # @Eval(agent=CodeReviewer) + 2 @Metrics
  tests/
    conftest.py                   # no-op; the universal provider needs no API key for ollama:*
    test_smoke.py                 # decorator + tool + stream metadata; no provider calls
```

## The model string and the env-var contract

The universal provider routes by **prefix**. For Ollama the spec is:

- `@Agent(model="ollama:llama3.3", ...)` — the prefix is `ollama:` and
  the bit after the colon is the SDK-level model name (`llama3.3`,
  `llama3.2`, `mistral`, `qwen2.5-coder`, etc.).
- Routing is wired in `src/ajolopy/providers/registry.py`
  (`("ollama:*", "universal-openai")`).
- The `UniversalOpenAIProvider` ships a per-prefix default base URL —
  for `ollama` the default is **`http://localhost:11434/v1`**.

There is **no provider env var to set for the Ollama prefix**. The
universal provider's `_PrefixDefaults.api_key_env` is `None` for
`ollama`, and the SDK is given the literal `"ollama"` placeholder so
`openai.AsyncOpenAI` does not reject the empty key. A user wanting a
**remote** Ollama instance overrides the per-prefix base URL via the
constructor's `base_urls=` kwarg or — for the magical-default path —
passes a custom base URL when constructing the provider. The example
documents the default-magic path (`localhost:11434`) and points at the
constructor kwarg as the escape hatch.

`.env.example` therefore ships **only one optional variable**:

```bash
# Optional — only set if you point Ajolopy at a non-default Ollama URL.
# The framework uses http://localhost:11434/v1 out of the box and does
# not read this variable; it is here for users who run a remote Ollama
# (e.g. on a workstation) and want to set the base URL via the
# UniversalOpenAIProvider constructor escape hatch.
OLLAMA_BASE_URL=http://localhost:11434/v1

APP_ENV=development
LOG_LEVEL=debug
```

No `ANTHROPIC_API_KEY`, no `OPENAI_API_KEY`, no `OPENAI_BASE_URL`. The
provider does not read `OPENAI_BASE_URL`; only the `api_keys=` /
`base_urls=` constructor kwargs (or the per-prefix env var, which is
`None` for Ollama). The variable in `.env.example` is purely
documentation for the escape hatch.

## The agent

`src/local_ollama/agents/reviewer.py` decorates `CodeReviewer`:

```python
@Agent(
    model="ollama:llama3.3",
    system=(
        "You review Python code. Be concise and concrete. "
        "Always call lint_function with the user's code first; quote any "
        "syntax error verbatim. Then give two or three specific suggestions "
        "(naming, types, idioms, bugs) — no preamble, no closing pleasantry."
    ),
)
class CodeReviewer:
    @Tool
    async def lint_function(self, code: str) -> dict[str, str | bool]: ...

    @Stream("/chat")
    async def respond(self, body: Annotated[ReviewRequest, Body()]) -> AsyncGenerator[str]: ...
```

The agent is intentionally minimal — one tool, one route, one model
string. No `fallback=` (the wedge user has only one Ollama daemon
running, so the framework's retriable-failure fallback would point at
the same broken server). The README documents how to add a hosted
fallback when going to production.

## The tool — `lint_function`

`lint_function(code: str)` runs `ast.parse(code)` and returns:

```python
{"ok": True, "error": ""}                # parses cleanly
{"ok": False, "error": "<SyntaxError msg at line N>"}   # syntax error
```

Pure stdlib (`ast`, `typing`). No network, no subprocess, no third-party
dependency. The tool exists to demonstrate the function-calling loop end
to end without leaking the example into a real linter dependency tree.
The tool's docstring instructs the model to call it on every request so
the syntax check runs before the model spends tokens reviewing broken
code.

## The stream contract

`@Stream("/chat")` accepts a Pydantic body:

```python
class ReviewRequest(BaseModel):
    code: str
```

Matches the tutorial pattern (`Annotated[ReviewRequest, Body()]`). The
handler delegates to `self.stream(body.code)` and yields chunks straight
through to the SSE response.

## Sample data

`data/code-samples.jsonl` ships **5 Python snippets** with deliberately
seeded issues. The shape per row:

```json
{
  "id": "unused-import",
  "code": "import os\n\ndef add(a, b):\n    return a + b\n",
  "issue": "unused import"
}
```

The seeded issues span: unused import, missing return type, off-by-one
in a loop, mutable-default-argument, and a deliberate syntax error
(unbalanced parenthesis) so the `lint_function` tool can demonstrate a
non-`ok=True` branch on at least one row.

## The eval suite

`evals/reviewer_eval.py` wires
`@Eval(agent=CodeReviewer, dataset="evals/reviewer.jsonl", threshold=0.6)`
with two metrics:

- **`identifies_issue`** — LLM-as-judge via
  `ajolopy.eval.metrics.llm_judge(output.text, criterion="...",
  model="ollama:llama3.3", cache=True)`. The judge is the same local
  Ollama model — keeping the example self-contained on a laptop. The
  criterion encodes "answer correctly identifies the seeded issue from
  `expected.issue`".
- **`response_within_budget`** — deterministic per-case scorer. Passes
  when the response text is non-empty and shorter than ~500 tokens
  (`len(output.text.split()) < 500` is the cheap proxy; aggregator
  `mean`, `pass_threshold=0.8`).

`ajolopy eval --ci` discovers `ReviewerEval` automatically when invoked
from the example's project root. The README notes that the eval suite
requires a running Ollama server with `llama3.3` pulled, same as the
agent itself.

## The deploy story (with caveat)

`Dockerfile.prod` and `.dockerignore` are pre-generated snapshots of
`ajolopy deploy docker`. `fly.toml` is the `ajolopy deploy fly`
snapshot. **All three ship despite Ollama not being deployable to Fly**
so the example stays consistent with `examples/support-agent/` and
`dogfood/docsbot/` (every runnable Ajolopy project ships the same
deploy artifacts so readers can compare diffs).

The README has a prominent caveat block:

> **Deploying Ollama is non-trivial.** Ollama runs on the user's
> machine, not on Fly / Railway / Render. Three options when promoting
> this example to production:
>
> 1. Run your own Ollama (k8s with a GPU node, or a long-lived VPS) and
>    point the universal provider at it with the `base_urls=` constructor
>    kwarg.
> 2. Swap `model="ollama:llama3.3"` for a hosted OpenAI-compatible
>    prefix the framework already routes — `groq:llama-3.3-70b-versatile`,
>    `together:meta-llama/Llama-3.3-70B-Instruct-Turbo`, etc. — and add
>    that provider's API key to `.env`.
> 3. Replace the universal-provider model string with a cloud provider
>    (`claude-opus-4-7`, `gpt-4o`, `gemini-1.5-pro`) — Ajolopy's
>    multi-provider design means swapping is a one-line change.

The `Dockerfile.prod` itself is unchanged from the standard Ajolopy
snapshot — it just builds the Python service.

## Acceptance criteria

- [ ] `examples/local-ollama/` exists with the structure documented above.
- [ ] `examples/local-ollama/src/local_ollama/agents/reviewer.py` defines
      a `CodeReviewer` `@Agent(model="ollama:llama3.3", ...)`. No
      `trace=` kwarg. System prompt is concise and instructs the model
      to call `lint_function` first.
- [ ] `examples/local-ollama/src/local_ollama/agents/reviewer.py` defines
      a `lint_function` `@Tool` that calls `ast.parse(code)` and returns
      `{"ok": bool, "error": str}`. Pure stdlib — no third-party imports.
- [ ] `examples/local-ollama/src/local_ollama/agents/reviewer.py` defines
      a `@Stream("/chat")` handler with
      `body: Annotated[ReviewRequest, Body()]` where
      `ReviewRequest(BaseModel)` has a single `code: str` field.
- [ ] `examples/local-ollama/src/local_ollama/__init__.py` performs the
      side-effect import of `ajolopy.providers.universal_openai` (not
      `anthropic`) so `@Agent(model="ollama:llama3.3", ...)` resolves at
      decoration time.
- [ ] `examples/local-ollama/.env.example` is minimal: no API keys,
      `OLLAMA_BASE_URL` as documented escape hatch, plus `APP_ENV` /
      `LOG_LEVEL`. The header comment makes the "no API key required"
      point explicit.
- [ ] `examples/local-ollama/data/code-samples.jsonl` ships **at least
      five** Python snippets with seeded issues spanning unused import,
      missing return type, off-by-one, mutable default arg, and a
      syntax error.
- [ ] `examples/local-ollama/evals/reviewer.jsonl` ships at least five
      cases that match the eval suite's dataset shape (`{"input": str,
      "expected": {"issue": str}}`).
- [ ] `examples/local-ollama/evals/reviewer_eval.py` wires
      `@Eval(agent=CodeReviewer, dataset="evals/reviewer.jsonl", ...)`
      with the `identifies_issue` (LLM-judge using `llm_judge`, async,
      kwarg-only) and `response_within_budget` (deterministic) metrics
      described above.
- [ ] `examples/local-ollama/pyproject.toml` uses `[tool.uv.sources]` to
      point `ajolopy` at the parent repo
      (`{ path = "../..", editable = true }`).
- [ ] `examples/local-ollama/README.md` walks the reader from
      installing Ollama through `ollama pull llama3.3`, `uv sync`,
      `ajolopy dev`, and at least one `curl` against `/chat`. Leans
      into the **no API key required** message in the first paragraph.
- [ ] `examples/local-ollama/Dockerfile.prod`, `.dockerignore`, and
      `fly.toml` are snapshotted versions of the framework's deploy
      output, parallel to `dogfood/docsbot/`. The README spells out the
      deploy caveat (Ollama runs locally; swap the model string for a
      hosted provider to deploy).
- [ ] `examples/local-ollama/tests/conftest.py` sets up whatever the
      universal provider needs at import time so `pytest` runs without
      a real Ollama daemon. For `ollama:*` no API key is required, so
      the file is largely a placeholder; if any env var is needed by
      the framework's import-time validation, set it here.
- [ ] `examples/local-ollama/tests/test_smoke.py` asserts the agent
      class is decorated (`_agent_runtime`), the tool carries
      `__ajolopy_tool__`, the `ReviewRequest` Pydantic model validates,
      and `respond` carries `@Stream` metadata pointing at `POST /chat`.
      No provider calls.
- [ ] Repository root `README.md` `## Examples` section gains a bullet
      pointing at `examples/local-ollama/`, calling out the
      no-API-key onboarding angle.
- [ ] `docs/next-steps.md` "Read real projects" list gains a bullet for
      `examples/local-ollama/` with the same angle.
- [ ] Root `pyproject.toml` `[tool.pyright]` gains the
      `examples/local-ollama` and `examples/local-ollama/tests` execution
      environments so strict typing covers the new example, mirroring
      the AJ-50 entries.
- [ ] `uv run ruff check examples/local-ollama` passes.
- [ ] `uv run ruff format --check examples/local-ollama` passes.
- [ ] `uv run pyright examples/local-ollama` passes (strict).
- [ ] From inside the example directory:
      `cd examples/local-ollama && uv sync && uv run pytest tests/`
      passes (smoke only).

## Out of scope

- Actually deploying Ollama to a cloud target. The README documents the
  three escape-hatch options (run your own Ollama, swap to a hosted
  OpenAI-compatible prefix, or swap to a cloud provider) but does not
  ship a recipe for any.
- A second agent or a workflow. v0.1's multi-agent example is AJ-50.
- Real linter integration (`ruff`, `pyright`). The `lint_function` tool
  stays at `ast.parse` so the example has zero third-party dependencies.
- Embedding-based eval (semantic similarity over the ground-truth
  answer). The eval uses the same local Ollama judge so the demo stays
  self-contained.
- A demo video. That is AJ-57.

## Implementation notes

- **The universal provider's env-var contract.** Despite the natural
  reach for `OPENAI_BASE_URL`, the `UniversalOpenAIProvider` does NOT
  read it. Per-prefix endpoint overrides go through the constructor's
  `base_urls={"ollama": "http://my-ollama.lan:11434/v1"}` kwarg. The
  example ships the default-magic path (`localhost:11434`) and leaves
  the override as a documented escape hatch. The `OLLAMA_BASE_URL`
  variable in `.env.example` is **documentation only** — the framework
  does not consume it; readers wiring a remote Ollama instance subclass
  the provider or pass the kwarg.
- **Side-effect import target.** The example imports
  `ajolopy.providers.universal_openai`, not `anthropic`. That import
  registers `UniversalOpenAIProvider` under the `"universal-openai"` key,
  which the registry's `("ollama:*", "universal-openai")` rule then
  routes to.
- **API drift between the AJ-48 tutorial and current source.** `@Agent`
  in v0.1 has **no `trace=` kwarg** — OTel is always on, no-op without
  the `otel` extra. The example honours the current API.
- **`@Stream` body shape.** The current contract is
  `Annotated[Model, Body()]` (not `Body(Model)` or `body: Model`). The
  smoke test pins the metadata layout (`metadata.path == "/chat"`,
  `metadata.method == "POST"`).
- **`llm_judge` signature.** `async def llm_judge(output, *,
  criterion, model, expected=None, scale="0-1", cache=False,
  provider=None)`. Keyword-only after `output`. The example calls it
  `await llm_judge(output.text, criterion=..., model=...,
  cache=True)`.
- **No `fallback=` on the Ollama agent.** A single-laptop Ollama
  daemon has nothing to fall back to. The README documents adding a
  hosted fallback (e.g.
  `fallback="groq:llama-3.3-70b-versatile"`) when the example moves to
  production.
- **Pyright strict on the new project.** The root `pyproject.toml`
  `[tool.pyright]` `executionEnvironments` block already lists per-
  project entries for AJ-50 and AJ-54. This example adds two parallel
  entries (`examples/local-ollama` and
  `examples/local-ollama/tests`) so strict typing covers the new tree.
- **No CI invocation of `uv sync` on the example.** Same convention as
  AJ-50 / AJ-54: the smoke test runs from inside the example's own
  project, not the repo-level CI. Only `uv run pyright` and `uv run
  ruff check` cover the tree from the root.
- **Originality.** The reviewer scenario is original to this example.
  Code, prompts, dataset, README text are written from scratch — no
  copying from external tutorials, blog posts, or other repositories.
