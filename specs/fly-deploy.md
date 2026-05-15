# AJ-42 — Fly.io deploy target (`fly.toml` generator + flow)

> Tracked in [`board.json`](../board.json) as `AJ-42`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source-of-truth for the design: Brief v4.0 §10 + vault doc
> `07 - Deploy y Docker`, section `## ajolopy deploy fly`. If this file
> ever conflicts with the Brief or doc 07, those documents win.

## What

Land the real `FlyTarget` adapter so `ajolopy deploy fly` stops being a
stub. `AJ-37` established the `DeployTarget` Protocol + registry + the
reference `DockerTarget`; this item slots the first cloud target into the
same registry.

`FlyTarget` is a pure target (no I/O, no subprocess): it maps a
`DeployContext` to a `DeployResult` containing a single file
(`fly.toml`) plus the post-write commands the user runs themselves.

## Why

Brief v4.0 calls multi-deploy a v0.1 **non-negotiable**: "Fly.io +
Railway + Render + Vercel + Dockerfile universal". Fly.io is the
canonical small-app cloud for the wedge user (AI Engineer at a Series
A startup); shipping its target first unblocks the other three cloud
follow-ups by setting the exemplar pattern for them all.

## Public surface

```python
from ajolopy.cli.deploy.fly import FlyTarget
```

`FlyTarget` is auto-registered at `ajolopy.cli.deploy` import time. The
in-tree `FlyStub` is **removed**; the registry no longer needs a stub
slot for `fly`.

## Generated `fly.toml`

The exact shape comes from `07 - Deploy y Docker`, section
`## ajolopy deploy fly`. The renderer interpolates two values from the
`DeployContext`:

- `<project-name>` → `ctx.project_name`
- `<port>` → `ctx.port`

Every other field is a literal from the Brief.

```toml
app = "<project-name>"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[env]
  APP_ENV = "production"

[[services]]
  protocol = "tcp"
  internal_port = <port>

  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [services.concurrency]
    type = "connections"
    hard_limit = 50
    soft_limit = 25

[checks]
  [checks.health]
    type = "http"
    interval = "30s"
    timeout = "5s"
    grace_period = "30s"
    method = "get"
    path = "/health"
```

Rendering uses pure f-strings — no TOML library at runtime — to match
the AJ-41 Dockerfile renderer style. Tests parse the rendered string
with stdlib `tomllib` to assert structure.

The `[build] dockerfile` field intentionally points at `Dockerfile`
(no suffix). `ajolopy deploy docker` writes `Dockerfile.prod`; the
Fly flow expects users to rename or symlink to `Dockerfile` per the
Brief — that adapter step is the user's, not the framework's.

## `next_steps` output

Verbatim from the Brief, yielded in order:

```
fly auth login
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set DATABASE_URL=postgresql://...
fly launch
fly deploy
```

The two `fly secrets set` lines carry placeholder values
(`sk-ant-...`, `postgresql://...`) — they exist as visible reminders
of which secrets to set, not as literal commands.

## Source layout

- `src/ajolopy/cli/deploy/fly.py` — `FlyTarget` class.
- `src/ajolopy/cli/deploy/__init__.py` — drop the `FlyStub` import +
  register `FlyTarget()` in the same slot (registration order remains
  `docker, fly, railway, render, vercel`).
- `src/ajolopy/cli/deploy/stubs.py` — remove the `FlyStub` class.
  `RailwayStub`, `RenderStub`, `VercelStub` are untouched.
- `tests/cli/deploy/test_fly.py` — new test module.
- `tests/cli/deploy/test_stubs.py` — drop the `FlyStub` row from the
  parametrize list + remove the `FlyStub` import.
- `tests/cli/commands/test_deploy.py` — drop the `("fly", "AJ-42")`
  row from the stub parametrize + add a new test asserting the real
  `fly.toml` is written.
- `docs/reference/cli-deploy.md` — update the `fly` row in the v0.1
  target table.

## Acceptance criteria

Each item has at least one passing test before the board item
transitions to `done`.

### `FlyTarget` implementation

- [ ] `FlyTarget.name == "fly"`.
- [ ] `FlyTarget.description` mentions "Fly.io".
- [ ] `prepare()` returns exactly one file keyed `Path("fly.toml")`
      with a non-empty string body.
- [ ] The rendered `fly.toml` parses cleanly with `tomllib.loads`.
- [ ] Parsed `app == ctx.project_name`.
- [ ] Parsed `primary_region == "iad"`.
- [ ] Parsed `build.dockerfile == "Dockerfile"`.
- [ ] Parsed `env.APP_ENV == "production"`.
- [ ] Parsed `services[0].internal_port == ctx.port` and
      `services[0].protocol == "tcp"`.
- [ ] `services[0].ports` includes the entries for port 80
      (`handlers=["http"]`, `force_https=true`) and 443
      (`handlers=["tls", "http"]`).
- [ ] `services[0].concurrency` matches `type="connections"`,
      `hard_limit=50`, `soft_limit=25`.
- [ ] `checks.health` matches the Brief's
      `type/interval/timeout/grace_period/method/path` values.

### `next_steps`

- [ ] `next_steps(ctx, result)` yields exactly five strings in this
      order: `fly auth login`, `fly secrets set ANTHROPIC_API_KEY=...`,
      `fly secrets set DATABASE_URL=...`, `fly launch`, `fly deploy`.

### Stub removal + registry

- [ ] `ajolopy.cli.deploy` no longer exports `FlyStub` (the
      `__all__` list drops `FlyStub` and adds `FlyTarget`).
- [ ] `register_target(FlyTarget())` is invoked at import time in the
      same slot the stub previously occupied; the registration order
      stays `docker, fly, railway, render, vercel`.
- [ ] `get_target("fly")` returns a `FlyTarget` instance.

### Command integration

- [ ] `ajolopy deploy fly` against an empty `tmp_path` exits 0,
      writes exactly `fly.toml`, and prints the five next-step
      commands.
- [ ] `tests/cli/commands/test_deploy.py::test_stub_target_writes_nothing`
      no longer parametrizes `("fly", "AJ-42")`.

### Documentation

- [ ] `docs/reference/cli-deploy.md` — the `fly` row in the v0.1
      target table reflects the real behaviour (generates `fly.toml`
      + prints the `fly launch` / `fly deploy` flow), not the stub
      message.
- [ ] `uv run --group docs mkdocs build --strict` passes.

### Quality gates

- [ ] `uv run ruff check src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py tests/cli/deploy tests/cli/commands/test_deploy.py` — clean.
- [ ] `uv run ruff format --check` over the same files — clean.
- [ ] `uv run pyright src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py` — `0 errors`.
- [ ] `uv run pytest tests/cli/deploy tests/cli/commands/test_deploy.py` — green.

## Out of scope

- Invoking `flyctl` / `fly` from the command — v0.1 prints the
  commands but does not shell out to them. Same rationale as AJ-37:
  hermetic tests, no platform-specific dependencies on developer
  machines or CI runners.
- Multi-region deployment — `primary_region = "iad"` is the v0.1
  default per the Brief. Region overrides are a post-v0.1 follow-up
  (`AJ-XX` to be filed when the wedge user asks for it).
- Process / VM size tuning. The `fly.toml` produced here is the
  minimum that lands a working app on Fly; users edit by hand or
  follow Fly's docs for vertical scaling.
- Auto-generation of `Dockerfile` (the `[build] dockerfile` field
  points at `Dockerfile`, not `Dockerfile.prod`) — the user is
  expected to have run `ajolopy deploy docker` and renamed the
  output (or wired the path themselves). Cross-target glue is
  post-v0.1.

## Implementation pointers

- The renderer is a pure f-string concatenation, mirroring
  `src/ajolopy/templates/docker/dockerfile.py`. Two-space indentation
  on nested TOML tables matches the Brief exactly.
- `FlyTarget` lives at the same layer as `DockerTarget`. Both are
  thin adapters; the renderer is the same module so there is no
  separate `ajolopy.templates.fly` for v0.1 (the renderer is small
  enough to live alongside the target).
- The Protocol's `next_steps` accepts `result` for forward
  compatibility with future interactive targets. `FlyTarget` does
  not need it; `del result` keeps `pyright` happy.

## Implementation notes

Empty for now. Append entries during the work in chronological order
with a `YYYY-MM-DD` prefix.
