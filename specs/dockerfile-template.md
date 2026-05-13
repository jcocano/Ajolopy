# AJ-41 — Dockerfile multi-stage template + docker-compose generator

> Tracked in [`board.json`](../board.json) as `AJ-41`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §11 (deploy targets) +
> `07 - Deploy y Docker`. If this file ever conflicts with the Brief or doc
> 07, those documents win.

## What

A small, parametric template module that emits three deploy-time text
artifacts: a multi-stage `Dockerfile`, a `docker-compose.yml` skeleton
for local development, and a `.dockerignore`. The templates are pure
Python functions (no Jinja, no I/O, no extra dependency) so:

- `ajolopy new` (AJ-32) can call them when scaffolding a project.
- `ajolopy build` (AJ-38) can call `render_dockerfile()` to write
  `Dockerfile.prod` next to the user's code.
- `ajolopy deploy` (AJ-37) and the per-target items (AJ-42 / AJ-43 /
  AJ-44 / AJ-45) can compose `render_dockerfile()` output with their
  own target-specific manifest.

The functions return `str`; callers decide where to write the bytes.
This keeps the template module pure (testable without filesystem
fixtures) and keeps every CLI command's "what file goes where"
decision local to that command.

## Why

Doc 07 lists the Dockerfile and the development `docker-compose.yml` as
the universal deploy artifact every generated Ajolopy project ships
with on day one. Brief v4.0 §11 reinforces it: every supported deploy
target (Fly, Railway, Render, k8s, VPS) consumes this Dockerfile.
Centralising the template stops six different CLI subcommands from
diverging on the same multi-stage layout — every project picks up the
same security baseline (non-root prod user, healthcheck, slim runtime)
and the same dependency story (`uv sync --frozen`).

## Public surface (v0.1)

```python
from ajolopy.templates.docker import (
    render_dockerfile,
    render_docker_compose,
    render_dockerignore,
    DatabaseChoice,
)

dockerfile_text: str = render_dockerfile(
    python_version="3.14",
    app_module="main:app",
    port=3000,
)

compose_text: str = render_docker_compose(
    databases=("postgres", "redis"),
    app_port=3000,
)

dockerignore_text: str = render_dockerignore()
```

### Signatures

```python
DatabaseChoice = Literal["postgres", "pgvector", "redis", "qdrant"]


def render_dockerfile(
    *,
    python_version: str = "3.14",
    app_module: str = "main:app",
    port: int = 3000,
    workers: int = 4,
) -> str: ...


def render_docker_compose(
    *,
    databases: Sequence[DatabaseChoice] = (),
    app_port: int = 3000,
    target: Literal["development", "production"] = "development",
) -> str: ...


def render_dockerignore() -> str: ...
```

- `python_version` is a string so `"3.14"` and `"3.14-slim"` both work
  (`render_dockerfile` will normalise it into a `FROM python:<X>-slim`
  line; passing a tag suffix like `-slim` already present is a no-op).
  Invalid versions (`""`, non-`X.Y` format) raise `ValueError` at call
  time.
- `app_module` is `"<module>:<asgi_callable>"`, the same convention
  Uvicorn expects.
- `port` and `app_port` are integers; `< 1` or `> 65535` raises.
- `workers` is the prod `--workers` count; defaults to 4 per doc 07.
- `databases` is an ordered tuple so the compose file's service order
  is deterministic (snapshot tests rely on this).

### Default Dockerfile structure

Mirrors doc 07 exactly:

- Stage 1 (`deps`) — `python:<version>-slim`, installs `uv`, copies
  `pyproject.toml` + `uv.lock*`, runs `uv sync --frozen --no-dev`.
- Stage 2 (`development`) — extends `deps`, runs `uv sync --frozen`
  (re-includes dev deps), copies the source, exposes the port, sets
  `CMD` to `uvicorn ... --reload`.
- Stage 3 (`production`) — extends `deps`, copies the source, creates
  a non-root `appuser`, sets `USER appuser`, exposes the port, adds a
  `HEALTHCHECK` that curls `/health`, sets `CMD` to
  `uvicorn ... --workers <N> --no-access-log`.

The file always opens with `# syntax=docker/dockerfile:1.7` so BuildKit
features (`--mount=type=cache`) are available to callers that want to
extend the template downstream.

### Default `docker-compose.yml` structure

- `app` service builds from `Dockerfile` with the selected `target`,
  binds the volume, forwards the env file, and exposes `app_port`.
- One service per selected database:
  - `postgres` → `postgres:16-alpine` with `pg_isready` healthcheck.
  - `pgvector` → `pgvector/pgvector:pg16` (same healthcheck as
    `postgres`; `pgvector` and `postgres` are mutually exclusive in
    the same compose file).
  - `redis` → `redis:7-alpine` with `redis-cli ping` healthcheck.
  - `qdrant` → `qdrant/qdrant:latest` (no native healthcheck — emit a
    `# TODO: healthcheck` comment so users know the gap).
- A named volume per stateful service (`pgdata`, `qdrantdata`).

When `databases=()` the `depends_on` block on `app` is omitted entirely
so the file is still valid `docker compose config`.

### Default `.dockerignore`

Doc 07's list verbatim:

```
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.env
.env.local
.env.*.local
.vscode/
.idea/
*.swp
tests/
docs/
.github/
.git/
README.md
```

## Design rules

- **Pure functions.** No file I/O, no template-engine dependency, no
  third-party YAML library at call time. The renderers return `str`.
  Snapshot tests pin the output bit-for-bit; semantic tests parse the
  output with `yaml.safe_load` from the stdlib (or `pyyaml` if it
  becomes a dev dep) to confirm structural validity.
- **No silent defaults that drift from doc 07.** Every choice in this
  template that goes against the doc (different base image, different
  worker count) must be paired with a one-line code comment naming the
  reason. Future contributors reading the template see *why* the
  framework picked that knob.
- **Output is reproducible.** Same kwargs → same bytes. No timestamps,
  no random suffixes, no environment-dependent expansion. CI snapshot
  tests assume identical output across machines.
- **Postgres / pgvector are mutually exclusive in one compose file.**
  pgvector ships its own Postgres image, so allowing both would
  produce two Postgres services. Passing `("postgres", "pgvector")`
  raises `ValueError`.

## Out of scope for this item

- `ajolopy build` / `ajolopy deploy` CLI commands → `AJ-37` / `AJ-38`.
- Per-target deploy manifests (`fly.toml`, `railway.json`,
  `render.yaml`, `vercel.json`) → `AJ-42` / `AJ-43` / `AJ-44` /
  `AJ-45`.
- k8s manifests → v0.3 (per doc 07).
- The wizard prompts that surface `databases=` to the user → `AJ-32`.
- Image-build CI integration / smoke deploy tests → `AJ-52` (deploy
  recipes).

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`. Tests are pure-Python: render output is a
string compared against a snapshot, or parsed and asserted on. No
real Docker daemon is invoked in CI.

### `render_dockerfile()`

- [x] Default `render_dockerfile()` output:
  - opens with `# syntax=docker/dockerfile:1.7`,
  - contains exactly three `FROM` lines (`deps`, `development`,
    `production`),
  - `FROM python:3.14-slim AS deps` is the first base image,
  - the production stage `RUN`s `useradd -m appuser`, has `USER appuser`,
  - the production stage's `HEALTHCHECK` curls `http://localhost:3000/health`,
  - the production `CMD` includes `--workers 4 --no-access-log`.
- [x] `python_version="3.13"` swaps the base image to
      `python:3.13-slim` across all three stages.
- [x] `python_version="3.14-slim"` is normalised (no
      `python:3.14-slim-slim` in the output).
- [x] `port=8080` updates both the `EXPOSE` line and the healthcheck
      target URL in the production stage.
- [x] `app_module="api:app"` is forwarded to every Uvicorn `CMD`.
- [x] `workers=2` updates only the production `CMD`'s `--workers`
      value; the development stage stays on `--reload`.
- [x] `python_version=""` and `python_version="3"` raise `ValueError`
      naming the expected `X.Y` format.
- [x] `port=0` and `port=70_000` raise `ValueError`.

### `render_docker_compose()`

- [x] `databases=()` produces a single `app` service with no
      `depends_on` block.
- [x] `databases=("postgres",)` adds a `db` service backed by
      `postgres:16-alpine`, the `pg_isready` healthcheck, a `pgdata`
      named volume, and `app.depends_on.db.condition: service_healthy`.
- [x] `databases=("pgvector",)` swaps the image to
      `pgvector/pgvector:pg16` and keeps the same healthcheck +
      volume name.
- [x] `databases=("postgres", "pgvector")` raises `ValueError`
      naming the mutual exclusion.
- [x] `databases=("redis",)` adds a `redis` service backed by
      `redis:7-alpine` with the `redis-cli ping` healthcheck and
      `app.depends_on.redis.condition: service_healthy`.
- [x] `databases=("qdrant",)` adds a `qdrant` service backed by
      `qdrant/qdrant:latest` with the `qdrantdata` volume and a
      `# TODO: healthcheck` comment line directly above the service.
- [x] `databases=("postgres", "redis", "qdrant")` emits all three
      services in that order, all three named volumes, and a
      `depends_on` block that references every healthy service.
- [x] `target="production"` drops the bind mount (`./:/app`) from the
      `app` service and changes `build.target` to `production`.
- [x] The output parses cleanly with `yaml.safe_load` and the
      top-level structure is `{"services": {...}, "volumes": {...}}`
      when any stateful service is selected, or `{"services": {...}}`
      when none.

### `render_dockerignore()`

- [x] Output contains every doc 07 entry exactly once; the order
      matches the doc for reviewability.
- [x] No leading / trailing blank lines (so concatenation with a
      user-provided extension is well-behaved).

### Snapshot stability

- [x] A snapshot test pins the default output of each renderer to a
      committed `.txt` fixture under `tests/templates/docker/__snapshots__/`.
      Diffing the snapshot is the canonical signal that the template
      changed; CI fails until the snapshot is regenerated and
      reviewed.

## Implementation pointers

- Source: `src/ajolopy/templates/__init__.py` (re-exports) +
  `src/ajolopy/templates/docker/__init__.py` package containing:
  - `dockerfile.py` — `render_dockerfile`.
  - `compose.py` — `render_docker_compose` plus the
    `DatabaseChoice` literal and the per-service emitters.
  - `dockerignore.py` — `render_dockerignore` (single function).
  - `errors.py` (optional) — none needed if `ValueError` is enough.
- Tests: `tests/templates/docker/` mirroring the source layout, one
  test file per renderer + a `__snapshots__/` folder for the
  bit-for-bit fixtures.
- Runtime deps: none new. The templates are string literals and
  f-strings; no Jinja, no Pydantic, no PyYAML at runtime. Dev deps:
  `PyYAML` for the parse-and-assert tests (already transitive via
  several existing dev deps; pin it explicitly via `uv add --dev`
  with a one-line justification in the PR description).
- The renderers should be **deterministic**: avoid any code that
  iterates over a `dict` whose key order depends on Python's hash
  randomisation. Sequence the database services through the
  `databases=` tuple, not through a set or unordered map.

## Implementation notes

- **Package layout** matches the spec verbatim: `src/ajolopy/templates/__init__.py`
  re-exports the docker subpackage's public surface, and
  `src/ajolopy/templates/docker/{__init__.py, dockerfile.py, compose.py,
  dockerignore.py}` host the renderers. No top-level export from
  `ajolopy` — `from ajolopy.templates.docker import ...` is the only entry
  point.
- **Renderers are pure f-strings + concatenation.** No template engine, no
  YAML serializer at render time, no `textwrap.dedent` (the f-string
  literals are written at the indentation they will appear in the output,
  which made the diff vs doc 07 easier to eyeball). PyYAML stays a
  test-only dependency.
- **Determinism** is enforced by (a) `databases` being a `Sequence`, never
  a set or dict, and (b) `_VOLUME_BY_DB` only being read in the order
  `databases` lists. The snapshot tests double-check.
- **`postgres`/`pgvector` mutual exclusion** is enforced by checking the
  intersection of `databases` against a `frozenset({"postgres",
  "pgvector"})` and raising before any service block is emitted.
- **Duplicate detection** (`databases=("postgres", "postgres")`) raises
  the same way, since duplicate service keys would also produce an invalid
  compose document.
- **Qdrant TODO comment** is emitted one line directly above
  `  qdrant:` (verified by a test that does `lines.index("  qdrant:")`
  and asserts the line above). The compose file still parses cleanly via
  `yaml.safe_load`.
- **Redis owns no top-level volume.** Doc 07 omits one for the dev
  compose example, and a stateful Redis is not the default story; the
  `_VOLUME_BY_DB` map only includes `pgdata` and `qdrantdata`. The
  `volumes:` top-level block is dropped entirely when no stateful service
  is selected (e.g. `databases=("redis",)`), so the parsed structure
  matches `{"services": {...}}` cleanly.
- **`target="production"`** drops the bind mount (`./:/app`) and sets
  `build.target` to `production`. The semantics test parses the YAML and
  asserts `"volumes" not in app`.
- **`port=0`** is rejected on both `render_dockerfile(port=...)` and
  `render_docker_compose(app_port=...)` with the same `1..65535` range,
  even though TCP allows 0 as a kernel-assigned port — `EXPOSE 0` is
  meaningless in a Dockerfile.
- **PyYAML** was added as a dev dependency via `uv add --dev pyyaml`. It
  was already transitive through several existing test deps, but pinning
  it explicitly makes the dev-time intent visible in `pyproject.toml`.
- **Sequence import** is wrapped in `if TYPE_CHECKING` so the runtime
  module stays import-free of `collections.abc`. PEP 649 (Python 3.14)
  handles the lazy annotation resolution.
- **Coverage**: the templates package lands at 100% on all three
  renderers. Mutual exclusion, duplicate detection, and the qdrant
  TODO comment placement each have a dedicated test.
