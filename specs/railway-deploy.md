# AJ-43 — Railway deploy target

> Tracked in [`board.json`](../board.json) as `AJ-43`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §10 + vault doc
> `07 - Deploy y Docker`, section `## ajolopy deploy railway`. If this file
> ever conflicts with the Brief or doc 07, those documents win.

## What

Replace the in-tree `RailwayStub` with a real `RailwayTarget` that
implements the `DeployTarget` protocol (`AJ-37`) and emits the
`railway.json` manifest documented in Brief v4.0 §10 / vault doc 07.

The target is **pure**: `prepare` builds the `railway.json` contents in
memory; the command driver does every filesystem write and stdout
print. v0.1 does NOT invoke the `railway` CLI — `next_steps` only
prints the three commands the user runs themselves.

## Why

Brief v4.0 names Railway as one of the four cloud targets that have to
ship in v0.1 (`Fly.io + Railway + Render + Vercel + Dockerfile
universal`). `AJ-37` landed the gateway command + protocol + registry
with a stub for Railway; `AJ-43` lands the real manifest generator so
`ajolopy deploy railway` is no longer a placeholder.

## Design rule

Follow the **magical default + escape hatch** pattern that every
deploy target obeys:

- **Magical default**: `RailwayTarget` reads the standard inputs from
  `DeployContext` (`app_module`, nothing else for now — port comes from
  Railway's `$PORT`) and renders the Brief's verbatim template. No
  configuration knobs in v0.1.
- **Escape hatch**: users who need a custom Railway manifest implement
  `DeployTarget` themselves and `register_target(MyRailwayTarget())`
  after import. The registry's last-write-wins semantics promote the
  override without touching the framework.

## Manifest — `railway.json`

Verbatim from Brief v4.0 §10 / vault doc 07. `<app_module>` is
substituted from `ctx.app_module`; everything else is a constant.

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile",
    "buildTarget": "production"
  },
  "deploy": {
    "startCommand": "uvicorn <app_module> --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

Rendering rules:

- Use `json.dumps(..., indent=2, sort_keys=False)` so the top-level
  ordering (`$schema`, `build`, `deploy`) and nested key ordering match
  the Brief.
- The file ends with a single trailing newline.
- The output is UTF-8 (the default for `Path.write_text` in the
  command driver).

### `DeployContext` fields consumed

| Field        | Used for                                                   |
| ------------ | ---------------------------------------------------------- |
| `app_module` | substituted into `deploy.startCommand`'s `uvicorn` call    |

Every other `DeployContext` field is currently irrelevant to Railway
(port comes from Railway's `$PORT` env, project name is not surfaced
in the manifest). Targets stay free to consume additional fields in
follow-up items.

## Next steps printed

Verbatim from the Brief, in this order:

```
railway login
railway link            # link to an existing project
railway up              # deploy
```

`next_steps` yields three strings, the command driver renders them
under the standard `Next steps:` header.

## Public surface change

```python
# src/ajolopy/cli/deploy/__init__.py
from .railway import RailwayTarget           # NEW
from .stubs import FlyStub, RenderStub, VercelStub   # RailwayStub dropped
register_target(RailwayTarget())             # replaces RailwayStub()

# src/ajolopy/cli/deploy/stubs.py
# RailwayStub class removed; FlyStub / RenderStub / VercelStub stay.
```

The registration order stays `docker, fly, railway, render, vercel`
so `ajolopy deploy --help` lists targets in the same sequence.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### `RailwayTarget`

- [ ] `name == "railway"`, `description` mentions `"Railway"`.
- [ ] `prepare(ctx)` returns exactly one file: `Path("railway.json")`
      → non-empty string contents.
- [ ] The rendered string parses cleanly with `json.loads`.
- [ ] Top-level keys are `$schema`, `build`, `deploy`.
- [ ] `build.builder == "DOCKERFILE"`,
      `build.dockerfilePath == "Dockerfile"`,
      `build.buildTarget == "production"`.
- [ ] `deploy.startCommand` contains both `ctx.app_module` and the
      literal `$PORT` placeholder.
- [ ] `deploy.healthcheckPath == "/health"`,
      `deploy.healthcheckTimeout == 30`,
      `deploy.restartPolicyType == "ON_FAILURE"`,
      `deploy.restartPolicyMaxRetries == 3`.
- [ ] `next_steps(ctx, result)` yields three strings in order:
      `railway login`, `railway link`, `railway up`.

### Wiring

- [ ] `RailwayStub` no longer exists in `src/ajolopy/cli/deploy/stubs.py`.
- [ ] `src/ajolopy/cli/deploy/__init__.py` imports `RailwayTarget`
      from `.railway`, registers it in the same slot as the old stub,
      and exports it from `__all__`.
- [ ] `tests/cli/deploy/test_stubs.py` drops the `RailwayStub` row +
      import.
- [ ] `tests/cli/commands/test_deploy.py` drops the
      `("railway", "AJ-43")` parametrize row from the stub test and
      adds a positive test that `ajolopy deploy railway` writes
      `railway.json`, prints the three next-step commands, and exits 0.
- [ ] `docs/reference/cli-deploy.md`'s v0.1 targets table replaces the
      Railway stub note with a description of the real behaviour.

### Quality gates

- [ ] `uv run ruff check src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py tests/cli/deploy tests/cli/commands/test_deploy.py` — zero violations.
- [ ] `uv run ruff format --check` over the same files — clean.
- [ ] `uv run pyright src/ajolopy/cli/deploy src/ajolopy/cli/commands/deploy.py` — `0 errors`.
- [ ] `uv run pytest tests/cli/deploy tests/cli/commands/test_deploy.py` — green.
- [ ] `uv run --group docs mkdocs build --strict` — passes.

## Out of scope

- Invoking the `railway` CLI from inside `ajolopy deploy railway`.
  v0.1 prints the commands; the user runs them. This keeps the test
  suite hermetic and avoids shelling out to a tool the CI environment
  does not have.
- Custom Railway service / multi-service manifests. v0.1 emits a
  single-service `railway.json` matching the Brief verbatim; users who
  need multi-service deployments override the target.
- Reading Railway-specific config from `pyproject.toml` (no
  `[tool.ajolopy.railway]` table in v0.1).
- Health-check / restart-policy customisation. The Brief pins these
  values; configurability lands when there is a concrete request.

## Implementation pointers

- Source: `src/ajolopy/cli/deploy/railway.py` (new module).
- Tests: `tests/cli/deploy/test_railway.py` (new module).
- Renderer: stdlib `json.dumps(..., indent=2, sort_keys=False)`. The
  template is short enough that a Jinja round-trip is overkill.
- Mirror the shape of `DockerTarget` (`AJ-37`): `ClassVar` `name`/
  `description`, pure `prepare`, `next_steps` returns an `Iterable[str]`
  built once.
- Keep registration order in `__init__.py` stable: `docker, fly,
  railway, render, vercel`. The Help output and the test in
  `test_deploy.py::test_help_description_lists_every_target` rely on
  it.

## Implementation notes

- `2026-05-15` — spec drafted from Brief v4.0 §10 / vault doc 07
  during the AJ-43 claim. Three sibling agents (AJ-42, AJ-44, AJ-45)
  are touching `__init__.py` / `stubs.py` / `test_stubs.py` /
  `test_deploy.py` / `cli-deploy.md` in parallel; expect rebase
  conflicts on those files when the first of them merges.
