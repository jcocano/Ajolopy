# AJ-47 — Quickstart docs (5 min to hello world) + mkdocs-material setup

> Tracked in [`board.json`](../board.json) as `AJ-47`. Absorbs AJ-53 (mkdocs
> site setup) per the user's scoping decision — the docs site bootstraps
> here.

## What

1. **mkdocs-material site setup** at the repo root (`mkdocs.yml` +
   `docs/`).
2. **Quickstart content** under `docs/`: index, install, hello world,
   next steps.
3. Local-dev story: `uv run mkdocs serve` works.

## Why

Brief dolor #7: "Onboarding nuevo dev → 2 semanas leyendo código".
The Quickstart is the first thing the user reads. Without it, the
framework is invisible.

## Public surface (v0.1)

### Files added

```
mkdocs.yml                         # mkdocs-material config
docs/
  index.md                         # Landing page + value prop
  quickstart.md                    # 5-min hello-world
  install.md                       # uv add ajolopy, extras
  next-steps.md                    # pointers to tutorial / reference
  stylesheets/extra.css            # minor brand polish
  assets/                          # logo placeholder
```

### `mkdocs.yml`

```yaml
site_name: Ajolopy
site_description: AI-native production framework for Python
repo_url: https://github.com/jcocano/Ajolopy
repo_name: jcocano/Ajolopy
edit_uri: edit/main/docs/

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - content.code.copy
    - content.code.annotate
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: indigo

nav:
  - Home: index.md
  - Quickstart: quickstart.md
  - Install: install.md
  - Next steps: next-steps.md

markdown_extensions:
  - admonition
  - attr_list
  - pymdownx.highlight
  - pymdownx.superfences
  - pymdownx.inlinehilite
  - pymdownx.snippets
  - pymdownx.tabbed:
      alternate_style: true

extra_css:
  - stylesheets/extra.css
```

### `docs/quickstart.md` — must achieve

The reader has a working agent in <5 minutes:

```markdown
# Quickstart — 5 minutes to your first agent

## 1. Install (30 seconds)

uv pip install ajolopy

## 2. Create a project (1 minute)

ajolopy new my-agent
cd my-agent
uv sync

## 3. Set your API key (30 seconds)

cp .env.example .env
# Edit .env to add ANTHROPIC_API_KEY=...

## 4. Run (1 minute)

ajolopy dev

## 5. Talk to it (2 minutes)

curl -X POST http://127.0.0.1:8000/chat -d '{"message": "hello"}'
```

### `docs/install.md` — must achieve

- Core install line.
- Optional extras matrix (otel, mcp, redis, postgres, mongo, qdrant,
  pgvector).
- Python version requirement (3.14+).

### `docs/next-steps.md` — must achieve

- Pointers to:
  - Tutorial (the 3-step arc — AJ-48).
  - Reference (the per-primitive docs — AJ-49).
  - Example projects (AJ-50 dogfood).
  - GitHub repo + issues.

## Cross-cuts

### `pyproject.toml` — additive
- Add `[dependency-groups] docs = ["mkdocs>=1.6", "mkdocs-material>=9.5"]`.
- `uv sync --group docs` enables the docs build.

### `.github/workflows/` — additive
- New `docs.yml` workflow: on push to main, builds the site and
  deploys to GitHub Pages. Use the standard
  `mkdocs gh-deploy` action. SHA-pinned per the project security
  baseline.

### `README.md` — additive (optional)
- Add a "📖 Docs" link to the new site URL near the top.

### AJ-49 (reference docs) — will EXTEND `mkdocs.yml`
- AJ-49 will add a `Reference:` section under `nav:`. Merge order:
  AJ-47 first, then rebase AJ-49.

## Out of scope

- Tutorial content (AJ-48 — the 3-step killer-demo arc).
- Per-primitive reference content (AJ-49).
- Recipes / cookbook (AJ-51 observability, AJ-52 deploy).
- Search infrastructure beyond mkdocs-material's built-in.

## Acceptance criteria

- [x] `uv run mkdocs serve` builds the site without errors.
- [x] `uv run mkdocs build` produces a `site/` directory.
- [x] `docs/quickstart.md` exists and follows the documented
      structure (5 sections).
- [x] `docs/install.md` lists every optional extra with one-line
      descriptions.
- [x] `docs/next-steps.md` links to AJ-48 / AJ-49 / AJ-50 / repo.
- [x] `mkdocs.yml` has the nav structure as documented.
- [x] `pyproject.toml` declares the `docs` dependency group.
- [x] `.github/workflows/docs.yml` exists and is SHA-pinned.

## Implementation pointers

- All work in `docs/` + `mkdocs.yml` + `pyproject.toml` + a single
  workflow file.
- Use code blocks with ` ```python` fenced syntax so highlighting
  works.
- Use admonitions (`!!! note`, `!!! warning`) for emphasis.
- No tests needed (docs-only PR). If the agent wants a simple smoke
  test, `mkdocs build --strict` in CI would catch broken refs —
  consider adding to the docs workflow.

## Implementation notes

- **mkdocs.yml** sets `strict: true` at the top level (in addition to the
  CLI flag) so any local `uv run mkdocs build` catches broken refs
  without the developer remembering the flag.
- **GitHub Pages deploy** uses the official
  `configure-pages` + `upload-pages-artifact` + `deploy-pages` flow
  rather than `mkdocs gh-deploy`. Reasons: no PAT needed, deploys via
  OIDC, `pages: write` is scoped to the deploy job (workflow default
  remains `contents: read`), and all three actions are SHA-pinned per
  SECURITY.md.
- **Strict build doubles as smoke test.** The `build` job runs on every
  push and PR and runs `mkdocs build --strict`; the `deploy` job only
  runs on push to main and is gated on the build job. PRs therefore
  get the docs gate without leaking deploy permissions.
- **Optional unit test** (`tests/test_docs.py`) parametrises over every
  `*.md` under `docs/` and asserts each declares a top-level `#`
  heading. Cheap confidence gate that catches the most common "page
  renders empty in nav" mistake without depending on mkdocs at test
  time.
- **`.gitignore`** now excludes `/site/` so local `mkdocs build` runs
  do not leak the rendered HTML into commits.
- **README.md** gets a one-line "Documentation / Quickstart / Install"
  link cluster near the top, no other prose changes.
