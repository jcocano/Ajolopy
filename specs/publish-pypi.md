# AJ-56 — Publish v0.1.0 to PyPI (versioning, release workflow, signed release)

> Tracked in [`board.json`](../board.json) as `AJ-56`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source-of-truth for the design: Brief v4.0 (release plan for v0.1) plus
> the project's [`SECURITY.md`](../SECURITY.md) supply-chain baseline. If
> this file ever conflicts with the Brief or `SECURITY.md`, those documents
> win.

## Goal

Ship the **release infrastructure** for Ajolopy v0.1.0. The deliverable is
**not** the v0.1.0 release event itself — that is `AJ-57` (launch comms).
After this item lands, the maintainer can cut v0.1.0 by tagging `v0.1.0` and
pushing the tag; everything else (build, attest, sign, publish, GitHub
release) runs automatically with **no long-lived secrets** in the repository.

Concretely, this item lands four things:

1. A versioning strategy (decided + documented below).
2. The release workflow (`.github/workflows/release.yml`).
3. Contributor-facing release docs (`docs/contributing/release.md`),
   wired into the mkdocs nav.
4. The PyPI trusted-publisher and sigstore-on-GitHub one-time setup steps
   the maintainer runs externally (documented; not automated).

## Versioning decision

**Choice: manual `__version__` in `src/ajolopy/__init__.py` plus a workflow
gate that asserts the pushed git tag matches.**

### What this means

- `pyproject.toml` keeps `version = "0.1.0"` (the static string under
  `[project]`).
- `src/ajolopy/__init__.py` keeps `__version__ = "0.1.0"` (same string —
  the framework's runtime API still exposes `ajolopy.__version__`).
- The release workflow refuses to publish if the tag does not equal
  `"v" + ajolopy.__version__`.

### Why this over hatch-vcs

`hatch-vcs` (tag-derived version) is the more "magical" option, but it has
two real costs for this project today:

- The runtime `__version__` becomes a generated file (`_version.py`) that
  is gitignored. Every existing import path that resolves
  `ajolopy.__version__` either keeps working or breaks depending on the
  order in which `__init__.py` evaluates — adding moving parts to a v0.1
  release is the wrong trade-off.
- The current `pyproject.toml` already ships a static `version = "0.0.1"`.
  Migrating to hatch-vcs is a refactor that touches the build backend
  config; doing it during the release-infra PR mixes two concerns.

The "static version + tag-match gate" pattern is what most v0.x Python
libraries that publish to PyPI via trusted publishing actually do (it is
the default in the `pypa/gh-action-pypi-publish` README's example). It is
boring, auditable, and the failure mode (tag mismatch) is loud and early.

If the maintainer later prefers tag-driven versions, switching to
`hatch-vcs` is a single PR — out of scope for this item.

### Version-bump policy for v0.1.x and beyond

- Pre-release: `0.1.0-rcN` is allowed (tag pattern `v0.1.0-rc1`,
  `v0.1.0-rc2`, ...). The workflow accepts both `v0.1.0` and `v0.1.0-rcN`
  shapes; in both cases the runtime `__version__` must equal the tag with
  the leading `v` stripped.
- Semantic-version bumps: minor for new primitives or breaking signature
  changes during the 0.x line; patch for fixes. After 1.0, follow strict
  SemVer.
- The bump is a single PR that edits two files (`pyproject.toml`,
  `src/ajolopy/__init__.py`) — easy to review, easy to revert.

## Release workflow stages

`.github/workflows/release.yml` triggers on a pushed tag matching
`v*.*.*` (with optional `-rcN` pre-release suffix). It runs five jobs;
each later job depends on the previous and is skipped if any pre-flight
check fails:

1. **`preflight`** — fast guards. Quality gates (`ruff check`,
   `ruff format --check`, `pyright`, `pytest`), the **tag-vs-`__version__`
   match check**, and `uv build` producing the wheel + sdist.
   Outputs `version` and the `dist/` artifacts.
2. **`twine-check`** — runs `uv run --with twine twine check` against the
   built artifacts. A clean wheel + sdist is the prerequisite to upload.
3. **`sign`** — runs `sigstore/gh-action-sigstore-python` against every
   file in `dist/` and uploads the `*.sigstore` bundles as artifacts.
   Requires `id-token: write` (OIDC against the sigstore public-good
   instance — no secrets).
4. **`publish`** — calls `pypa/gh-action-pypi-publish` with no token.
   Trusted publishing exchanges the workflow's OIDC token for a one-shot
   PyPI upload credential. Requires `id-token: write`. The job runs
   inside a GitHub Environment named `pypi` so the maintainer can require
   manual approval per release.
5. **`github-release`** — uses `softprops/action-gh-release` to create
   the GitHub release for the tag, attaching the wheel, the sdist, and
   every sigstore bundle. Requires `contents: write` (scoped to this
   job only).

Top-level `permissions: contents: read`. Every job widens permissions to
the **exact** scope it needs, never more.

### Why this layering (and not a single job)

- Pre-flight failures should not consume the OIDC tokens.
- The sign artifacts have to be produced before the GitHub release job
  attaches them, but **after** the wheel/sdist are clean.
- The publish job runs in its own GitHub Environment so the maintainer
  can require manual review.

### Pinned actions

Every third-party Action is pinned to a commit SHA (Dependabot updates
them weekly — see [`.github/dependabot.yml`](../.github/dependabot.yml)).
Tags are not acceptable.

| Action | Purpose | SHA pin source |
|---|---|---|
| `actions/checkout` | Source clone | Already pinned in `ci.yml` |
| `astral-sh/setup-uv` | Install uv + Python | Already pinned in `ci.yml` |
| `actions/upload-artifact` | Pass `dist/` between jobs | Already pinned in `ci.yml` |
| `actions/download-artifact` | Pass `dist/` between jobs | Already pinned in `ci.yml` |
| `sigstore/gh-action-sigstore-python` | Sign wheels + sdists | New — pinned to current published SHA |
| `pypa/gh-action-pypi-publish` | Trusted-publishing upload | Already pinned in existing draft release workflow |
| `softprops/action-gh-release` | Create the GitHub release | New — pinned to current published SHA |

## Pre-flight gate details

The `preflight` job runs **every** check that CI runs on a normal PR
(plus the tag-vs-`__version__` match):

- `uv sync --frozen` with every extra group used by typecheck (`otel`,
  `mcp`, `redis`, `postgres`, `mongo`, `qdrant`, `pgvector`) — keeps the
  release workflow honest if a future extra is added.
- `uv run ruff check`
- `uv run ruff format --check`
- `uv run pyright`
- `uv run pytest`
- **Tag match**: `tag=${GITHUB_REF_NAME}`, strip the leading `v`, compare
  against `python -c "import ajolopy; print(ajolopy.__version__)"`. Reject
  if different.
- `uv build --no-sources` — produces wheel + sdist in `dist/`.
- Upload `dist/` as an artifact for the downstream jobs.

If any of these fail, the release is aborted before any external side
effect (no PyPI upload, no GitHub release, no sigstore attestation).

## Security posture

- **No secrets for PyPI**. Trusted publishing (OIDC) handles the upload.
  The maintainer registers the repo as a trusted publisher on PyPI once
  (see "One-time PyPI setup" below). No `PYPI_TOKEN` ever exists.
- **Sigstore signatures** for every wheel + sdist. The bundles are
  uploaded as workflow artifacts and attached to the GitHub release so
  downstream consumers can verify provenance with the `sigstore` CLI.
- **Pinned SHAs** for every third-party Action. Dependabot updates them
  weekly per [`.github/dependabot.yml`](../.github/dependabot.yml).
- **Default-deny permissions**. Workflow top-level is
  `permissions: contents: read`. Jobs widen per their need — never the
  workflow itself.
- **No `PYPI_API_TOKEN`** anywhere — the workflow does not read from
  secrets at all.

## One-time PyPI setup (maintainer task)

This is the one part that has to happen on PyPI's side, exactly once,
before the very first release.

1. Visit <https://pypi.org/manage/account/publishing/> while logged in
   as the project owner.
2. Click "Add a new pending publisher" (or, if `ajolopy` already exists
   on PyPI, open the project page and use "Manage → Publishing").
3. Fill in:
   - PyPI Project Name: `ajolopy`
   - Owner: `jcocano`
   - Repository name: `Ajolopy`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
4. Save.

After this, any push of a `v*.*.*` tag to the repository runs the
release workflow; the trusted-publisher exchange happens automatically.
No PyPI token ever enters the repository.

### One-time sigstore setup

Sigstore signing against the public-good instance requires no setup at
all — the workflow's `id-token: write` permission is enough. The
maintainer does not need to register anything.

### One-time GitHub Environment

In repository **Settings → Environments**, create an environment named
`pypi`. Optionally configure:

- "Required reviewers" (recommended) — gives the maintainer a manual
  approval step between the sign and publish jobs.
- "Deployment branches and tags" → restrict to tag pattern `v*.*.*`.

This is referenced from the `publish` job via `environment: name: pypi`.

## Acceptance criteria

- [ ] `pyproject.toml` declares `version = "0.1.0"` under `[project]`.
- [ ] `src/ajolopy/__init__.py` declares `__version__ = "0.1.0"`.
- [ ] `.github/workflows/release.yml` exists with the five-job pipeline
  described above (preflight → twine-check → sign → publish →
  github-release), top-level `permissions: contents: read`, and every
  third-party Action pinned to a commit SHA.
- [ ] The `preflight` job asserts that the pushed tag (minus the leading
  `v`) equals `ajolopy.__version__`. A tag that disagrees fails the job.
- [ ] The `preflight` job runs `ruff check`, `ruff format --check`,
  `pyright`, and `pytest` before invoking `uv build`.
- [ ] The `publish` job uses `pypa/gh-action-pypi-publish` with **no**
  `password` / `PYPI_TOKEN`. OIDC trusted publishing only.
- [ ] The `sign` job uses `sigstore/gh-action-sigstore-python` against
  every file in `dist/` and uploads the `*.sigstore` bundles.
- [ ] The `github-release` job creates the GitHub release for the tag
  and attaches the wheel, the sdist, and every sigstore bundle.
- [ ] `docs/contributing/release.md` exists and explains: who can
  release, the version-bump policy, the tag-and-push command, the
  one-time PyPI / GitHub Environment setup, what to verify after the
  release runs.
- [ ] `mkdocs.yml` wires the new page into the nav under a top-level
  `Contributing:` section so `mkdocs build --strict` resolves the link.
- [ ] `uv build` locally produces `dist/ajolopy-0.1.0-py3-none-any.whl`
  and `dist/ajolopy-0.1.0.tar.gz` cleanly.
- [ ] `twine check dist/*` passes locally.
- [ ] `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`,
  and `uv run pytest` all pass.
- [ ] `uv run --group docs mkdocs build --strict` passes.

## Out of scope

- The actual v0.1.0 release event (running `git tag v0.1.0 && git push
  --tags`). That is the maintainer's job and is tracked separately
  under `AJ-57` (launch comms).
- Announcement copy / HN post / launch tweet — also `AJ-57`.
- TestPyPI dry-run support. We will rely on `rc` tags (`v0.1.0-rc1`,
  ...) for production-equivalent dry runs; the trusted publisher accepts
  pre-release tags identically and PyPI displays them but does not pin
  them as "latest".
- Migrating to `hatch-vcs`. Documented as the alternative; deferred until
  there is a concrete request.
- Automating the PyPI / GitHub Environment / branch-protection setup.
  These are one-time clicks on external surfaces and intentionally not
  in version control.

## Implementation notes

- A `release.yml` draft already exists in this repository from earlier
  scaffolding. This item supersedes that file: same name, broader scope
  (pre-flight gate, sigstore, GitHub release, environment).
- The `pypi` GitHub Environment has to be created in the repository
  settings UI before the first tag push; otherwise the `publish` job
  fails with a clear "environment not found" error. This is documented
  in `docs/contributing/release.md` so it is part of the maintainer's
  pre-release checklist.
- `softprops/action-gh-release` is the canonical action for "create a
  GitHub release and upload assets" in the ecosystem. It accepts a
  glob path for assets, so attaching `dist/*` plus the sigstore bundles
  is one step.
