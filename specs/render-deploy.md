# AJ-44 — Render deploy target (`ajolopy deploy render`)

> Tracked in [`board.json`](../board.json) as `AJ-44`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source-of-truth for the design: Brief v4.0 §10 + vault doc
> `07 - Deploy y Docker`, section "`ajolopy deploy render`". If this file
> ever conflicts with those documents, those documents win.

## Goal

Replace the in-tree `RenderStub` (registered by `AJ-37`) with a real
`RenderTarget` that implements the `DeployTarget` Protocol and emits a
`render.yaml` Blueprint that Render's dashboard consumes verbatim.
Render's deploys are git-based and their CLI is read-only, so the
target's `next_steps` simply tell the user to commit/push the file and
visit the Render Blueprints dashboard.

The target is the third real impl after `DockerTarget` (`AJ-37`) and is
peer to `AJ-42` (Fly), `AJ-43` (Railway), and `AJ-45` (Vercel).

## What ships

- `src/ajolopy/cli/deploy/render.py` — `RenderTarget` class.
- `register_target(RenderTarget())` replacing `register_target(RenderStub())`
  in `src/ajolopy/cli/deploy/__init__.py` (same display slot, so the
  ordering `docker, fly, railway, render, vercel` is preserved).
- `RenderStub` removed from `src/ajolopy/cli/deploy/stubs.py` (the
  other three stubs stay untouched).
- `tests/cli/deploy/test_render.py` — unit coverage for the target.
- Updated rows in `tests/cli/deploy/test_stubs.py` and
  `tests/cli/commands/test_deploy.py` to drop `RenderStub`.
- Updated row in `docs/reference/cli-deploy.md` describing the real
  behaviour.

## The `render.yaml` template

Per Brief v4.0 §10 / vault doc `07 - Deploy y Docker`:

```yaml
services:
  - type: web
    name: <project-name>
    runtime: docker
    dockerfilePath: ./Dockerfile
    dockerTarget: production
    plan: starter
    healthCheckPath: /health
    envVars:
      - key: APP_ENV
        value: production
      - key: PORT
        value: <port>
```

- `<project-name>` is `ctx.project_name`.
- `<port>` is `ctx.port`.
- The output is rendered with a pure f-string + concatenation, no
  PyYAML at runtime — same pattern as
  `ajolopy.templates.docker.compose`. Tests parse the output with
  `yaml.safe_load` (PyYAML is already a dev dependency).
- The output is fully deterministic for stable snapshots.

## Next steps the target prints

Render uses git-based deploys; their CLI is read-only. The
`next_steps` iterable yields exactly two strings, in order:

1. `Commit and push the generated render.yaml to your repo.`
2. `Visit https://dashboard.render.com/blueprints to apply the blueprint.`

The driver in `ajolopy.cli.commands.deploy` prepends a `Next steps:`
header and indents each line — same shape `DockerTarget` uses.

## Fields consumed from `DeployContext`

| Field              | Used for                                |
| ------------------ | --------------------------------------- |
| `project_name`     | `services[0].name` in `render.yaml`.    |
| `port`             | `envVars` entry `PORT`.                 |

All other context fields (`app_module`, `python_version`,
`project_root`, `is_tty`, `yes`, `dry_run`, `force`) are not read by
this target — the Dockerfile already encodes the app module and
Python version, and the command driver owns filesystem behaviour.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### `RenderTarget`

- [ ] `name == "render"` and `description` mentions "Render".
- [ ] `prepare()` returns exactly one file: `Path("render.yaml")` with
      a non-empty string body.
- [ ] The rendered YAML parses cleanly with `yaml.safe_load`.
- [ ] Parsed structure: `services` is a list with one entry.
- [ ] `services[0]` has fields `type == "web"`, `name == ctx.project_name`,
      `runtime == "docker"`, `dockerfilePath == "./Dockerfile"`,
      `dockerTarget == "production"`, `plan == "starter"`,
      `healthCheckPath == "/health"`.
- [ ] `services[0].envVars` is a list with two entries:
      `{key: "APP_ENV", value: "production"}` followed by
      `{key: "PORT", value: <ctx.port>}`.
- [ ] `next_steps()` yields exactly two strings: the commit-and-push
      reminder and the dashboard URL, in that order.

### Registry integration

- [ ] `ajolopy deploy render` against an empty `tmp_path` writes
      exactly `render.yaml`, prints both next-step strings, and exits 0.
- [ ] `RenderStub` is no longer importable from
      `ajolopy.cli.deploy.stubs` (the class is removed).
- [ ] `list_targets()` order remains `docker, fly, railway, render, vercel`.

### Documentation

- [ ] `docs/reference/cli-deploy.md` row for `render` describes the
      real behaviour (the `render.yaml` blueprint dashboard flow).
- [ ] `uv run --group docs mkdocs build --strict` passes.

### Quality gates

- [ ] `uv run ruff check src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py tests/cli/deploy tests/cli/commands/test_deploy.py` — zero violations.
- [ ] `uv run ruff format --check` — clean.
- [ ] `uv run pyright src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py` — `0 errors`.
- [ ] `uv run pytest tests/cli/deploy tests/cli/commands/test_deploy.py` — green.

## Out of scope for v0.1

- Invoking any Render REST API. Render's API is read-only for
  Blueprint apply flows; users apply via the dashboard.
- Generating supporting services (databases, redis, workers) in
  `render.yaml`. v0.1 ships exactly the single `web` service above.
  Multi-service blueprints land alongside `ajolopy new`'s multi-DB
  wizard (post-v0.1).
- Reading Render-specific env vars from `pyproject.toml` /
  `ajolopy.toml`. Today `envVars` is the fixed pair shown above; users
  with custom env vars edit the generated file by hand.
- Custom `plan` selection. The blueprint hard-codes `starter` per
  Brief; advanced users edit the file manually.
- Multi-region deploys, scaling configuration, or custom health-check
  paths. All deferred to a follow-up alongside other platform
  enhancements.

## Implementation pointers

- Match `DockerTarget`'s module shape: ClassVar `name` /
  `description`, pure `prepare`, `next_steps` returning an
  `Iterable[str]` tuple, module-level `__all__ = ["RenderTarget"]`.
- No third-party imports — the renderer is a function of two scalars
  (`project_name`, `port`).
- File constant: `_RENDER_YAML_NAME = "render.yaml"`.
- The two next-step strings are module-level constants so the test
  suite can assert against them by identity.
