# AJ-37 — `ajolopy deploy [target]`

> Tracked in [`board.json`](../board.json) as `AJ-37`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source-of-truth for the design: Brief v4.0 §10 + vault doc
> `07 - Deploy y Docker`. If this file ever conflicts with the Brief or doc
> 07, those documents win.

## What

A new CLI subcommand `ajolopy deploy <target>` that produces the per-target
deploy manifest (and, where it makes sense, executes the platform's CLI).
The command is the **gateway** for five deploy targets in v0.1:

| Target    | Manifest emitted        | Status in AJ-37                       | Owning item |
| --------- | ----------------------- | ------------------------------------- | ----------- |
| `docker`  | `Dockerfile.prod` + `.dockerignore` + on-screen `docker build` instructions | **Reference impl** ships here | AJ-37       |
| `fly`     | `fly.toml`              | Stub — prints "land via AJ-42"          | AJ-42       |
| `railway` | `railway.json`          | Stub — prints "land via AJ-43"          | AJ-43       |
| `render`  | `render.yaml`           | Stub — prints "land via AJ-44"          | AJ-44       |
| `vercel`  | `vercel.json` + warnings | Stub — prints "land via AJ-45"          | AJ-45       |

The stubs are deliberate placeholders so `ajolopy deploy --help` lists all
five targets from day one. AJ-42 / AJ-43 / AJ-44 / AJ-45 each replace their
stub with a real implementation by **dropping a new `DeployTarget` subclass
into the registry** — no churn to the dispatcher, the command surface, or
the help text. That registry split is the whole point of AJ-37: lock the
shape now so the 4 follow-ups never re-litigate it.

## Why

Brief v4.0 calls multi-deploy a v0.1 **non-negotiable**: "Fly.io + Railway
+ Render + Vercel + Dockerfile universal". Without `ajolopy deploy` the
five platform-specific manifests have to be hand-rolled by the user; with
it, the same project lands on any of them in one command. The reference
`docker` target also covers k8s / VPS / ECS / on-prem (the manifest is just
a Dockerfile), which is why v0.1 ships the docker case here rather than
waiting on a separate dedicated item.

`ajolopy deploy` is also the upstream of `AJ-52` (deploy recipes — five
docs pages that walk through each target's flow). AJ-52 cannot ship
believably until the command exists; landing AJ-37 (plus AJ-42–45) is the
prerequisite.

## Public surface (v0.1)

```bash
ajolopy deploy <target> [--dry-run] [--out <path>] [--force] [--yes]
```

| Argument / flag      | Type / values                                | Default       | Description |
| -------------------- | -------------------------------------------- | ------------- | ----------- |
| `target` (positional) | `Literal["docker", "fly", "railway", "render", "vercel"]` | required | Which deploy target to render. |
| `--dry-run`           | flag                                         | off           | Print the manifest(s) to stdout instead of writing to disk. Exit 0 on success. |
| `--out <path>`        | str                                          | cwd           | Project root where manifests should be written. Tested for write-access before any file is touched. |
| `--force`             | flag                                         | off           | Overwrite existing manifest files. Without it, an existing file aborts the command with a hint. |
| `--yes` / `-y`        | flag                                         | off           | Skip interactive confirmation prompts (used by `vercel` for the warning gate). |

Subcommand-internal Python entry points (the test seam):

```python
from ajolopy.cli.deploy import (
    DeployTarget,         # the Protocol every target implements
    DeployContext,        # frozen dataclass that wraps the runtime inputs
    DeployResult,         # frozen dataclass returned by `target.prepare()`
    DeployTargetError,    # base error
    DeployTargetNotFound,
    DeployFilesExist,
    register_target,
    get_target,
    list_targets,
)

from ajolopy.cli.deploy.docker import DockerTarget
from ajolopy.cli.deploy.stubs import FlyStub, RailwayStub, RenderStub, VercelStub
```

### `DeployTarget` protocol

```python
class DeployTarget(Protocol):
    name: ClassVar[str]                # "docker" / "fly" / ...
    description: ClassVar[str]         # one-line help-text blurb.

    def prepare(self, ctx: DeployContext) -> DeployResult: ...
    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]: ...
```

- `prepare` is **pure**: it returns the files that should be written
  (path + bytes), but it does NOT touch the filesystem. The command
  driver does the write, honouring `--dry-run` / `--force` / `--out`.
- `next_steps` returns the post-write instructions printed to stdout
  (`fly deploy`, `railway up`, `docker build && docker run`, etc.). A
  stub target returns its `"this target lands via AJ-XX"` message
  here.
- Targets that need user confirmation BEFORE writing (e.g. Vercel's
  warning gate) raise `DeployUserAbort` from `prepare`; the command
  driver converts the exception into a clean exit code without a
  Python traceback.

### `DeployContext`

```python
@dataclass(slots=True, frozen=True)
class DeployContext:
    project_root: Path        # validated to exist + be writable.
    app_module: str           # discovered from src/<pkg>/main.py:app, "main:app" otherwise.
    port: int                 # default 3000, configurable later.
    python_version: str       # "3.14" (from sys.version_info — matches the Dockerfile default).
    is_tty: bool              # whether stdout is interactive (drives prompt behaviour).
    yes: bool                 # `--yes` flag.
    dry_run: bool             # `--dry-run` flag.
    force: bool               # `--force` flag.
```

`DeployContext` is built once by the command driver and threaded into
every target. Targets MUST NOT mutate it.

### `DeployResult`

```python
@dataclass(slots=True, frozen=True)
class DeployResult:
    files: Mapping[Path, str]  # relative path → file contents (UTF-8).
    notes: tuple[str, ...] = ()
```

- `files` keys are relative to `ctx.project_root`. Writing absolute
  paths raises `DeployTargetError`.
- `notes` are informational lines printed under the file list (e.g.
  "Skipped Dockerfile because a Dockerfile already exists").

## Reference implementation — `DockerTarget`

The `docker` target is the v0.1 reference impl. It:

1. Calls `ajolopy.templates.docker.render_dockerfile(target="production")`
   plus `render_dockerignore()` (both AJ-41).
2. Returns `{ "Dockerfile.prod": <…>, ".dockerignore": <…> }` in `files`.
3. `next_steps` prints:
   - `docker build -f Dockerfile.prod -t <project-name>:latest .`
   - `docker run -p 3000:3000 --env-file .env <project-name>:latest`
4. If a `Dockerfile.prod` already exists and `--force` is off, the
   command driver short-circuits with `DeployFilesExist` (exit code 2).
   The user fixes manually or re-runs with `--force`.

`<project-name>` is derived from `pyproject.toml`'s `[project] name` (or
`Path.cwd().name` as fallback) at command-driver time — the target
itself stays pure.

## Stub targets — `FlyStub` / `RailwayStub` / `RenderStub` / `VercelStub`

Each stub:

1. Returns `DeployResult(files={}, notes=("This target ships in AJ-XX. See …",))`
   from `prepare`. **No files are emitted.**
2. Yields one human-readable line from `next_steps` pointing at:
   - The board item (`AJ-42` / `AJ-43` / `AJ-44` / `AJ-45`).
   - The relevant Brief v4.0 sections (so the user can read what the
     target *will* generate when AJ-X lands).
3. Sets `description` to e.g. `"Fly.io — manifest generation (ships in AJ-42)."` so `--help` is honest.

When AJ-42–45 each land, they call `register_target(FlyTarget())` (and
the others) AFTER `register_target(FlyStub())` so the registry's "last
in wins" semantics replace the stub. The registry exposes
`list_targets()` for `--help`, which iterates registration order and
de-duplicates by `name`.

## CLI surface notes

- The command lives at `src/ajolopy/cli/commands/deploy.py` and follows
  the same shape as `dev.py` / `doctor.py` / `eval.py`: a
  `register(sub)` function plus a `cmd_deploy(args) -> int` entry
  point.
- The package `src/ajolopy/cli/deploy/` holds the registry,
  Protocol, errors, docker target, and stubs:
  - `__init__.py` — re-exports the public symbols.
  - `base.py` — Protocol + `DeployContext` + `DeployResult`.
  - `registry.py` — module-level dict, `register_target` / `get_target`
    / `list_targets`.
  - `docker.py` — `DockerTarget` reference impl.
  - `stubs.py` — the four stubs.
  - `errors.py` — `DeployTargetError`, `DeployTargetNotFound`,
    `DeployFilesExist`, `DeployUserAbort`.
- The five stubs (`Fly`, `Railway`, `Render`, `Vercel`, plus the real
  `Docker`) register themselves at import-time inside
  `src/ajolopy/cli/deploy/__init__.py`. The dispatcher imports the
  package once, so `ajolopy deploy --help` always shows all five.
- Exit codes:
  - `0` — manifest(s) written (or `--dry-run` succeeded).
  - `1` — user aborted (vercel warning, missing pyproject.toml, etc.).
  - `2` — usage error (unknown target, missing args, files exist
    without `--force`).
  - `3` — internal target error (template rendering failed, IO failed).

## Out of scope for this item

- The four cloud targets' real implementations → AJ-42 (Fly), AJ-43
  (Railway), AJ-44 (Render), AJ-45 (Vercel).
- `ajolopy build` → AJ-38. `ajolopy build` is a *separate* CLI
  command that writes `Dockerfile.prod` + `.dockerignore` and prints
  instructions; `ajolopy deploy docker` deliberately overlaps in v0.1
  to give users a single mental model ("`ajolopy deploy <where>`"),
  but the AJ-38 command is the more focused entry point and lands in
  a follow-up. **Both** call `ajolopy.templates.docker.*` — no
  duplication.
- k8s manifests → v0.3 (per Brief v4.0 §8 List B).
- Actually invoking platform CLIs (`fly deploy`, `railway up`, etc.)
  → out of scope. v0.1 generates manifests and prints commands; the
  user runs them. This avoids us shelling-out to tools the test
  environment will not have and keeps CI hermetic.
- Image build invocation (`docker build …`) → out of scope. Same
  reason; the user runs the build, we hand them the command.

## Implementation pointers

- Source layout matches the [Public surface](#public-surface-v01)
  section verbatim. No re-exports from `ajolopy` top-level —
  `from ajolopy.cli.deploy import …` is the only entry point.
- Targets are pure. Filesystem I/O lives in the command driver
  (`_write_files`). Subprocess invocation lives in… nowhere; v0.1
  prints the commands but does not run them.
- The command driver depends on `ajolopy.templates.docker` (AJ-41)
  and is otherwise free of framework state — `ajolopy deploy` does
  NOT bootstrap `AjolopyFactory` (no DI container, no providers).
  This keeps the command fast (`ajolopy --help` cost is unchanged)
  and lets the tests stay hermetic.
- `pyproject.toml` parsing uses `tomllib` (stdlib in 3.11+, native in
  3.14). Missing `[project] name` is non-fatal — fall back to
  `Path.cwd().name`. Malformed `pyproject.toml` is fatal (exit code
  1 with a hint about the file path + parse error).
- All file paths returned by `prepare()` are validated relative + no
  `..` traversal + no absolute. The driver enforces this; targets
  that break the rule raise `DeployTargetError` at write time.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`. Tests are pure-Python: real filesystem
through `tmp_path`, subprocess invocations are NOT made by the
command itself (so no monkeypatching `subprocess` is required).

### Command surface

- [x] `ajolopy deploy` (no positional) prints usage and exits with
      code `2`.
- [x] `ajolopy deploy unknown` exits with code `2` and the error
      lists all five registered targets.
- [x] `ajolopy deploy --help` lists all five targets with their
      `description` strings; the order is the registration order.
- [x] `ajolopy deploy docker` against an empty `tmp_path` writes
      `Dockerfile.prod` and `.dockerignore`, prints the two
      `docker build` / `docker run` next-step lines, and exits 0.
- [x] `ajolopy deploy docker` against a `tmp_path` that already has
      `Dockerfile.prod` and no `--force` exits with code `2` and
      hints at `--force`.
- [x] `ajolopy deploy docker --force` overwrites the existing files.
- [x] `ajolopy deploy docker --dry-run` prints both files to stdout
      (with a `# <path>` header per file) and writes nothing.
- [x] `ajolopy deploy docker --out <other-path>` writes to the
      supplied path instead of cwd.
- [x] `--yes` / `-y` is accepted (no error) even when the target
      does not require confirmation; this keeps the CLI surface
      forward-compatible with AJ-45's Vercel warning gate.
- [x] Exit codes for the four error cases match the constants in
      `deploy.py` (`EXIT_OK`, `EXIT_USAGE`, `EXIT_USER_ABORT`,
      `EXIT_INTERNAL`).

### Registry

- [x] `register_target(Cls)` adds a target keyed by `Cls.name`.
- [x] Registering a name a second time replaces the earlier
      registration (the "last in wins" semantics AJ-42–45 rely on).
- [x] `get_target("docker")` returns the registered `DockerTarget`
      instance.
- [x] `get_target("nope")` raises `DeployTargetNotFound` with the
      list of known names in the message.
- [x] `list_targets()` returns the registration order, de-duplicated
      by `name`.

### `DockerTarget` reference impl

- [x] `prepare()` returns exactly two files: `Dockerfile.prod` and
      `.dockerignore`, both as relative `Path` objects.
- [x] The `Dockerfile.prod` output equals
      `render_dockerfile(target="production", python_version=…, app_module=…, port=…)`
      for the same context inputs.
- [x] The `.dockerignore` output equals `render_dockerignore()`.
- [x] `next_steps()` yields the two `docker build` / `docker run`
      lines, with the project name resolved from `pyproject.toml`'s
      `[project] name` when available and `Path.cwd().name`
      otherwise.

### Stub targets

- [x] `FlyStub.prepare()` returns `files={}` and a `notes` entry
      pointing at AJ-42.
- [x] Same for `RailwayStub` (AJ-43), `RenderStub` (AJ-44),
      `VercelStub` (AJ-45).
- [x] `next_steps()` yields one line per stub with the AJ-X link.
- [x] `ajolopy deploy fly` exits 0, writes nothing, and prints the
      stub message + AJ-42 pointer. Same for the three others.

### Documentation

- [x] `docs/reference/cli-deploy.md` exists with: purpose, signature,
      kwargs table, escape hatches (custom targets via
      `register_target`), common gotchas, see-also.
- [x] `mkdocs.yml` `nav:` extended under `Reference:` with a
      `"ajolopy deploy": reference/cli-deploy.md` entry, ordered
      alphabetically with the existing CLI entries.
- [x] `uv run --group docs mkdocs build --strict` passes.

### Quality gates

- [x] `uv run ruff check src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py tests/cli/deploy tests/cli/commands/test_deploy.py` — zero violations.
- [x] `uv run ruff format --check` — clean.
- [x] `uv run pyright src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py` — `0 errors`.
- [x] `uv run pytest tests/cli/deploy tests/cli/commands/test_deploy.py` — green.
- [x] Full repo `uv run pytest` — no new failures.
