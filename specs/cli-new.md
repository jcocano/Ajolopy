# AJ-32 — `ajolopy new <name>` wizard

> Tracked in [`board.json`](../board.json) as `AJ-32`. Generates a scaffolded
> Ajolopy project structure via 4 questions. The first user-facing
> on-ramp to the framework.

## What

`ajolopy new <project-name>` is a CLI subcommand that:

1. Validates the project name (kebab-case, lowercase, no path
   traversal).
2. Asks 4 questions interactively:
   - **Primary LLM**: anthropic / openai / gemini
   - **Example feature**: agent / workflow / mcp
   - **Include Dockerfile?**: y / n
   - **Include sample eval?**: y / n
3. Generates a NestJS-style minimal project structure under
   `./<project-name>/`.
4. Prints next-steps (uv sync, .env setup, ajolopy dev).

## Why

Brief v4.0 dolor #7: "Onboarding de un nuevo dev al AI app → ajolopy
new genera estructura por módulo (NestJS-style)". This is the on-ramp
that turns "I want to try the framework" into "I have a running app".

## Public surface (v0.1)

```bash
$ ajolopy new my-agent

? Primary LLM provider? [anthropic/openai/gemini] anthropic
? Example feature? [agent/workflow/mcp] agent
? Include Dockerfile? [y/n] y
? Include sample eval? [y/n] y

Creating my-agent/...
  ✓ pyproject.toml
  ✓ src/my_agent/__init__.py
  ✓ src/my_agent/main.py
  ✓ src/my_agent/app_module.py
  ✓ src/my_agent/agents/__init__.py
  ✓ src/my_agent/agents/support.py
  ✓ evals/__init__.py
  ✓ evals/support_eval.py
  ✓ evals/datasets/support.jsonl
  ✓ tests/__init__.py
  ✓ tests/test_support.py
  ✓ .env.example
  ✓ .gitignore
  ✓ Dockerfile
  ✓ README.md

Next steps:
  cd my-agent
  uv sync
  cp .env.example .env  # then fill in ANTHROPIC_API_KEY
  ajolopy dev
```

### CLI signature

```
ajolopy new <project-name> [--yes] [--llm <provider>] [--feature <kind>] [--no-docker] [--no-eval]
```

- `<project-name>` — required positional. Validated against
  `^[a-z][a-z0-9-]{1,40}$`. Path traversal / non-kebab → exit 2.
- `--yes` — non-interactive mode; uses defaults or the
  flag-supplied answers. Fails if a required answer is missing.
- `--llm` — pre-answer for primary LLM (anthropic/openai/gemini).
- `--feature` — pre-answer for example feature
  (agent/workflow/mcp).
- `--no-docker` / `--no-eval` — skip the Y/N prompts.

### Generated structure (NestJS-style)

```
my-agent/
  pyproject.toml                 # uv project with ajolopy + chosen provider extras
  uv.lock                        # NOT generated — user runs `uv sync` after
  README.md                      # quickstart + next-steps
  .env.example                   # documented env vars for chosen provider
  .gitignore                     # python + .env + .ajolopy/
  Dockerfile                     # multi-stage; OMITTED if --no-docker
  src/
    my_agent/
      __init__.py                # exports app
      main.py                    # builds app via AjolopyFactory.create(AppModule)
      app_module.py              # @Module wiring agents/workflows/evals
      agents/
        __init__.py
        support.py               # sample @Agent (or @Workflow per --feature)
  evals/
    __init__.py
    support_eval.py              # OMITTED if --no-eval
    datasets/
      support.jsonl              # 3 sample cases
  tests/
    __init__.py
    test_support.py              # smoke test (mocks provider)
```

### Templates

Static templates live in
`src/ajolopy/cli/commands/_templates/new/`. Files use `.tmpl`
extension where they need substitution; `.txt` / regular extensions
where they don't. The renderer uses `str.format(**ctx)` with these
substitution variables:

| Variable          | Example                       | Source                          |
|-------------------|-------------------------------|---------------------------------|
| `{project_name}`  | `my-agent`                    | kebab-case CLI arg              |
| `{package_name}`  | `my_agent`                    | snake-case derived              |
| `{class_prefix}`  | `MyAgent`                     | PascalCase derived              |
| `{llm_provider}`  | `anthropic` / `openai` / etc. | wizard answer                   |
| `{llm_model}`     | `claude-sonnet-4-7` / `gpt-4o`/ `gemini-2.0-flash-exp` | derived from provider |
| `{llm_env_var}`   | `ANTHROPIC_API_KEY` / etc.    | derived from provider           |
| `{llm_extra}`     | `anthropic` / `openai` / `gemini` | provider extra name        |
| `{feature}`       | `agent` / `workflow` / `mcp`  | wizard answer                   |

Per `--feature`:
- `agent` (default): generate a single `@Agent` with one `@Tool`
  method.
- `workflow`: generate 2 `@Agent` classes + a `@Workflow` coordinator.
- `mcp`: generate an `@Agent` with `integrations=[Integrations]`
  consuming the `github` MCP server example (commented-out token in
  `.env.example`).

### Provider → model defaults

| Provider   | Default model              | Env var               | Extra      |
|------------|----------------------------|-----------------------|------------|
| anthropic  | `claude-sonnet-4-7`        | `ANTHROPIC_API_KEY`   | (none — core dep) |
| openai     | `gpt-4o`                   | `OPENAI_API_KEY`      | (none — core dep) |
| gemini     | `gemini-2.0-flash-exp`     | `GOOGLE_API_KEY`      | (none — core dep) |

### Generated `pyproject.toml`

```toml
[project]
name = "{project_name}"
version = "0.0.1"
requires-python = ">=3.14"
dependencies = [
    "ajolopy>=0.1.0",
]

[tool.uv]
package = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]
```

### Generated `.env.example`

```bash
# Primary LLM provider
{llm_env_var}=

# App config
APP_ENV=development
LOG_LEVEL=debug

# (Add your own env vars below)
```

(For `--feature mcp`: adds `# GITHUB_PERSONAL_ACCESS_TOKEN=` comment.)

### Generated `main.py`

```python
"""Entry point. ``uvicorn {package_name}.main:app`` (or ``ajolopy dev``)."""

import asyncio

from ajolopy import AjolopyFactory

from {package_name}.app_module import AppModule


async def _build() -> object:
    return await AjolopyFactory.create(AppModule)


app = asyncio.get_event_loop().run_until_complete(_build()).asgi
```

### Generated `app_module.py`

```python
from ajolopy import Module

from {package_name}.agents.support import Support


@Module(agents=[Support])
class AppModule:
    """Root module wiring agents, workflows, controllers."""
```

### Generated `agents/support.py` (feature=agent)

```python
from ajolopy import Agent, Stream, Tool


@Agent(
    model="{llm_model}",
    system="You are {class_prefix}, a helpful assistant.",
)
class Support:
    """The on-call assistant."""

    @Tool
    def echo(self, text: str) -> str:
        """Return the input unchanged. Replace with real logic."""
        return text

    @Stream("/chat")
    async def respond(self, message: str):
        async for chunk in self.stream(message):
            yield chunk
```

(Workflow and MCP variants are analogous — see Implementation
pointers.)

### Generated `evals/support_eval.py` (when --no-eval is NOT set)

```python
from ajolopy import Eval, Metric
from ajolopy.eval.metrics import exact_match

from {package_name}.agents.support import Support


@Eval(agent=Support, dataset="evals/datasets/support.jsonl")
class SupportEval:
    @Metric
    def echoed(self, output, expected) -> float:
        return exact_match(output, expected["text"])
```

### Generated `evals/datasets/support.jsonl`

```
{"input": {"message": "hello"}, "expected": {"text": "hello"}}
{"input": {"message": "world"}, "expected": {"text": "world"}}
{"input": {"message": "test"}, "expected": {"text": "test"}}
```

### Generated `Dockerfile` (when --no-docker is NOT set)

Multi-stage; copied from `src/ajolopy/templates/docker/dockerfile.py`
(the AJ-41 template generator). Falls back to a static one if the
template generator is not available.

### Idempotency

- Refuses to write into an EXISTING directory unless `--force` is
  passed (NOT in v0.1; refuse outright). Exit 1 with "directory
  already exists".
- Refuses to write into the cwd directly (always creates a child).

## Cross-cuts

### AJ-60 (CLI dispatcher) — additive
- Register `new` subcommand in
  `src/ajolopy/cli/commands/__init__.py::register_subcommands`.

### AJ-41 (Dockerfile generator) — reuse
- If `from ajolopy.templates.docker import dockerfile` is available,
  use it. Otherwise fall back to a static `Dockerfile.tmpl`.

## Acceptance criteria

### CLI validation
- [ ] `ajolopy new MyAgent` (capitalised) exits 2 with "must be
      kebab-case".
- [ ] `ajolopy new ../bad` exits 2.
- [ ] `ajolopy new my-agent` with no existing dir succeeds.
- [ ] `ajolopy new existing-dir` exits 1 with "directory exists".

### Interactive wizard
- [ ] Without flags: prompts 4 questions sequentially.
- [ ] Each prompt accepts the documented values (lowercase
      validation).
- [ ] `Ctrl+C` mid-prompt aborts cleanly (exit 130 per shell
      convention).

### Non-interactive (`--yes`)
- [ ] `ajolopy new x --yes` uses defaults
      (anthropic/agent/y/y).
- [ ] `ajolopy new x --yes --llm openai --feature workflow
      --no-docker --no-eval` generates accordingly.

### Generated structure (feature=agent, llm=anthropic, docker=y, eval=y)
- [ ] Creates `./my-agent/` with the documented files.
- [ ] `pyproject.toml` declares `ajolopy>=0.1.0`.
- [ ] `main.py` references `{package_name}.app_module:AppModule`.
- [ ] `agents/support.py` uses `claude-sonnet-4-7`.
- [ ] `.env.example` lists `ANTHROPIC_API_KEY`.
- [ ] `evals/datasets/support.jsonl` has 3 lines.
- [ ] `Dockerfile` is present.
- [ ] `README.md` lists the next-step commands.

### Feature variants
- [ ] `--feature workflow` generates 2 agents + a workflow class.
- [ ] `--feature mcp` generates an `@MCP` integrations class +
      `@Agent(integrations=[...])`. `.env.example` includes the
      `GITHUB_PERSONAL_ACCESS_TOKEN` comment.

### Provider variants
- [ ] `--llm openai` uses `gpt-4o` and `OPENAI_API_KEY`.
- [ ] `--llm gemini` uses `gemini-2.0-flash-exp` and
      `GOOGLE_API_KEY`.

### Output
- [ ] Per-file `✓` lines as the writer creates each file.
- [ ] Final "Next steps" block with the documented commands.

### Smoke test
- [ ] The generated project, after `uv sync` in a tmp_path,
      imports cleanly: `python -c "import {package_name}.main"`
      succeeds with `--yes --llm anthropic --feature agent
      --no-eval --no-docker`. (Real LLM call NOT exercised.)

## Implementation pointers

- `src/ajolopy/cli/commands/new.py` — argparse + interactive prompts
  + template rendering. ~400 LoC including templates inlined.
- `src/ajolopy/cli/commands/_templates/new/` — `.tmpl` files for each
  generated file. Loaded via `importlib.resources` for installed-
  package safety.
- `src/ajolopy/cli/commands/__init__.py` — register `new.register(sub)`.
- Tests: `tests/cli/new/`.
  - `test_validation.py` — name / dir validation.
  - `test_wizard_interactive.py` — `input()` mocked with `pytest`'s
    `monkeypatch`.
  - `test_yes_mode.py` — full non-interactive path.
  - `test_generated_structure.py` — assert file paths + minimal
    content.
  - `test_feature_variants.py` — agent / workflow / mcp.
  - `test_smoke_import.py` — actually import the generated package
    in a tmp_path.

## Implementation notes

(Empty — populated by the implementation PR.)
