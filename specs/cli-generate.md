# AJ-34 — `ajolopy generate <kind> <name>` scaffolders

> Tracked in [`board.json`](../board.json) as `AJ-34`. Generates a single file
> (or small set) of a chosen Ajolopy primitive into an existing
> project. Companion to `ajolopy new` (AJ-32) for incremental
> scaffolding.

## What

`ajolopy generate <kind> <name> [options]` is a CLI subcommand that
writes one templated file (or a small directory) for the chosen kind
into the appropriate location in an existing Ajolopy project.

Supported kinds (v0.1, 7 total — from the board title):

| Kind         | Generates                                                 | Default path                                  |
|--------------|-----------------------------------------------------------|-----------------------------------------------|
| `agent`      | `@Agent`-decorated class with one `@Tool` method          | `src/<pkg>/agents/<name>.py`                  |
| `tool`       | Standalone tool class (rare — usually inside `@Agent`)    | `src/<pkg>/tools/<name>.py`                   |
| `workflow`   | `@Workflow` class + two `@Agent` placeholders             | `src/<pkg>/workflows/<name>.py`               |
| `eval`       | `@Eval` class + sample JSONL dataset                       | `evals/<name>_eval.py` + `evals/datasets/<name>.jsonl` |
| `controller` | `@Controller` class with `@Get` + `@Post` stubs           | `src/<pkg>/controllers/<name>_controller.py`  |
| `module`     | `@Module` skeleton (`imports`/`providers`/`controllers`)  | `src/<pkg>/<name>_module.py`                  |
| `service`    | `@Injectable` class skeleton                              | `src/<pkg>/services/<name>_service.py`        |

## Public surface (v0.1)

```bash
ajolopy generate <kind> <name> [--path <dir>] [--force]
```

- `<kind>` — one of the 7 documented kinds.
- `<name>` — snake_case identifier (validated against
  `^[a-z][a-z0-9_]*$`).
- `--path` — override the auto-resolved destination directory.
- `--force` — overwrite if the target file exists. Default: refuse.

### Auto-detection

Looks for `src/<single-package>/` in cwd (same convention as
`ajolopy dev` from AJ-33). The package name is used for imports in
the rendered template. `--path` overrides this.

### Templates

Stored as `.tmpl` files in `src/ajolopy/cli/commands/_templates/generate/<kind>/`.
Loaded via `importlib.resources`. Same substitution layer as AJ-32:

| Variable          | Example          | Source                            |
|-------------------|------------------|-----------------------------------|
| `{kind}`          | `agent`          | the subcommand kind               |
| `{name}`          | `support`        | the user-supplied name            |
| `{class_name}`    | `Support`        | PascalCase of `{name}`            |
| `{package_name}`  | `my_agent`       | auto-detected package             |
| `{snake_name}`    | `support`        | name (already snake)              |

### Exit codes

- `EXIT_OK=0`
- `EXIT_USAGE=2` — argparse / bad kind/name
- `EXIT_NO_PROJECT=1` — no `src/<pkg>/` found and no `--path`
- `EXIT_EXISTS=1` — target exists without `--force`

## Cross-cuts

### AJ-60 (CLI dispatcher) — additive
- Register `generate` subcommand in
  `src/ajolopy/cli/commands/__init__.py::register_subcommands`.

### AJ-32 (templates infra) — reuse
- Reuse `_templates/`-loading infrastructure from `new.py` (extract
  shared helpers into `src/ajolopy/cli/commands/_template_engine.py`
  if useful; keep it small).

## Out of scope

- Multi-file generation per kind beyond what's documented (e.g.,
  generating tests alongside the source) → v0.2 with `--with-tests`
  flag.
- Generating `@MCP` or `@MCPServer` integrations → v0.2.
- Interactive prompts (`ajolopy generate` without args) → v0.2.

## Acceptance criteria

- [ ] `ajolopy generate agent support` produces
      `src/<pkg>/agents/support.py` with a `class Support(Agent)`-like
      shell using `@Agent` + one `@Tool` method.
- [ ] `ajolopy generate workflow team` produces
      `src/<pkg>/workflows/team.py` with `@Workflow(...)` + two
      placeholder `@Agent` references.
- [ ] `ajolopy generate eval support` produces TWO files:
      `evals/support_eval.py` + `evals/datasets/support.jsonl` (with
      one placeholder case).
- [ ] `ajolopy generate controller users` →
      `src/<pkg>/controllers/users_controller.py` with `@Controller`
      + `@Get`/`@Post` stubs.
- [ ] `ajolopy generate module billing` →
      `src/<pkg>/billing_module.py` with `@Module(...)` skeleton.
- [ ] `ajolopy generate service notifier` →
      `src/<pkg>/services/notifier_service.py` with `@Injectable`
      skeleton.
- [ ] `ajolopy generate tool foo` → standalone tool stub.
- [ ] `ajolopy generate bogus name` → `EXIT_USAGE` listing valid kinds.
- [ ] `ajolopy generate agent BadName` (PascalCase) → `EXIT_USAGE`
      with snake_case hint.
- [ ] Existing target file without `--force` → `EXIT_EXISTS`.
- [ ] `--force` overwrites.
- [ ] `--path /tmp/x` writes to that path.
- [ ] No `src/<pkg>/` and no `--path` → `EXIT_NO_PROJECT`.
- [ ] Two packages under `src/` → `EXIT_NO_PROJECT` with hint to
      pass `--path`.

## Implementation pointers

- `src/ajolopy/cli/commands/generate.py` — argparse + auto-detection
  + dispatch table per kind + template loader.
- `src/ajolopy/cli/commands/_templates/generate/<kind>/*.tmpl` —
  the per-kind templates.
- Tests: `tests/cli/generate/` with one test file per kind plus a
  shared conftest that constructs a fake project tree in `tmp_path`.

## Implementation notes

(Empty — populated by the implementation PR.)
