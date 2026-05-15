# Releasing Ajolopy

This page documents how a release of Ajolopy is cut. The release pipeline
is automated end-to-end — the maintainer's job is to bump the version,
push a tag, and (optionally) approve the deploy in the GitHub Environment.
Everything else runs in
[`.github/workflows/release.yml`](https://github.com/jcocano/Ajolopy/blob/main/.github/workflows/release.yml).

## Who can release

The maintainer of the GitHub repository (`jcocano`) is the only person who
can cut a release. The trusted-publisher binding on PyPI is locked to
this exact repository + workflow + environment combination, so a fork
cannot accidentally publish.

## What the pipeline does on a tag push

When a tag matching `v*.*.*` (or `v*.*.*-rc*` for release candidates) is
pushed, the workflow runs five jobs in sequence:

1. **`preflight`** — `ruff check`, `ruff format --check`, `pyright`,
   `pytest`, the tag-vs-`__version__` match check, and `uv build`.
2. **`twine-check`** — `twine check` against the built wheel + sdist.
3. **`sign`** — `sigstore/gh-action-sigstore-python` produces a sigstore
   bundle for every artifact.
4. **`publish`** — `pypa/gh-action-pypi-publish` uploads to PyPI via
   trusted publishing (OIDC, no secrets).
5. **`github-release`** — `softprops/action-gh-release` creates the
   GitHub release for the tag and attaches the wheel, the sdist, and
   the sigstore bundles.

If any earlier job fails, the later jobs do not run. The release is
all-or-nothing.

## Version-bump policy

Ajolopy follows [semantic versioning](https://semver.org/) once it
reaches 1.0. During the 0.x line:

- **Patch** (`0.x.Y` → `0.x.Y+1`) — bug fixes, doc updates, no
  user-visible API change.
- **Minor** (`0.X.0` → `0.X+1.0`) — new primitive, new option on an
  existing primitive, or any breaking signature change. The 10-primitive
  contract still holds; minor bumps inside 0.x are the project's only
  way to land breaking changes.
- **Release candidates** (`0.X.0-rc1`, `0.X.0-rc2`, ...) — full
  dry-run publish through the same pipeline. PyPI accepts them but does
  not mark them as the project's "latest" version. The GitHub release
  is marked as a pre-release automatically.

The version lives in two places:

- `[project] version = "0.X.Y"` in
  [`pyproject.toml`](https://github.com/jcocano/Ajolopy/blob/main/pyproject.toml).
- `__version__ = "0.X.Y"` in
  [`src/ajolopy/__init__.py`](https://github.com/jcocano/Ajolopy/blob/main/src/ajolopy/__init__.py).

Both must match. The `preflight` job asserts that the pushed tag minus
the leading `v` equals `ajolopy.__version__`; a mismatch fails the
release before any external side effect.

## Cutting a release — step by step

```bash
# 1. From a clean main, bump both files to the target version.
git switch main
git pull --ff-only
# Edit pyproject.toml and src/ajolopy/__init__.py to the new version.

# 2. Commit on a chore branch and PR-merge to main.
git switch -c chore/release-0.X.Y
git commit -am "chore(release): bump to 0.X.Y"
git push -u origin chore/release-0.X.Y
# Open + merge the PR.

# 3. Once the bump is on main, tag and push.
git switch main
git pull --ff-only
git tag v0.X.Y
git push --follow-tags
```

The release workflow starts on the tag push. The maintainer can monitor
it under **Actions → Release**.

## One-time setup (per repository)

These steps are done **once**, before the very first release. They are
not in version control because they configure external surfaces (PyPI,
GitHub Settings).

### 1. Register the trusted publisher on PyPI

1. Visit
   [PyPI → Account → Publishing](https://pypi.org/manage/account/publishing/).
2. If the project does not exist yet, click **Add a new pending
   publisher**. If it does, open the project page and use
   **Manage → Publishing**.
3. Fill in the form:
    - **PyPI project name**: `ajolopy`
    - **Owner**: `jcocano`
    - **Repository name**: `Ajolopy`
    - **Workflow name**: `release.yml`
    - **Environment name**: `pypi`
4. Save.

After this, no PyPI token has to live anywhere — the workflow's OIDC
identity is what authenticates uploads.

### 2. Create the `pypi` GitHub Environment

1. In the repo, go to **Settings → Environments → New environment**.
2. Name it **`pypi`** (must match the workflow's
   `environment: name: pypi`).
3. Configure (optional but recommended):
    - **Required reviewers**: add the maintainer. With this on, the
      workflow pauses between the `sign` and `publish` jobs and waits
      for a manual approval — a final human gate before anything
      reaches PyPI.
    - **Deployment branches and tags**: restrict to `v*.*.*` and
      `v*.*.*-rc*` to ensure only tag-driven runs can deploy.

### 3. Sigstore — nothing to do

Sigstore signing against the public-good instance is keyless and
maintainer-free. The workflow's `id-token: write` permission is all it
needs.

## Verifying a release after the workflow runs

1. **PyPI**: the new version appears at
   <https://pypi.org/project/ajolopy/>. `pip install ajolopy==0.X.Y`
   should succeed.
2. **GitHub release**: the tag has an associated release at
   <https://github.com/jcocano/Ajolopy/releases>, with the wheel, the
   sdist, and the `*.sigstore` bundles attached.
3. **Sigstore verification** (optional but recommended for the
   maintainer):

    ```bash
    # Download a wheel + its sigstore bundle from the GitHub release.
    pip install sigstore
    sigstore verify identity \
      --cert-identity-regexp '^https://github\.com/jcocano/Ajolopy/' \
      --cert-oidc-issuer https://token.actions.githubusercontent.com \
      ajolopy-0.X.Y-py3-none-any.whl
    ```

    A clean exit means the wheel was signed by this repository's
    workflow.

## Failure modes and recovery

| Symptom | Cause | Recovery |
|---|---|---|
| `preflight` fails on the tag match | Tag does not match `__version__` | Delete the bad tag (`git tag -d`, `git push --delete origin`), bump the source files, re-tag, re-push. |
| `preflight` fails on lint / types / tests | A regression slipped past CI | Land the fix on main, re-bump version if needed, re-tag. |
| `publish` fails with "trusted publisher not configured" | One-time PyPI setup was skipped | Configure the trusted publisher on PyPI (see above) and re-run the failed job from the Actions tab. |
| `publish` fails with "environment not found" | The `pypi` GitHub Environment is missing | Create the environment in the repo settings and re-run the failed job. |
| `publish` succeeds but the wheel is missing on PyPI | Caching / propagation delay | Wait 1–2 minutes. PyPI's CDN is eventually consistent. |
| The sigstore step fails with "could not get OIDC token" | The job is missing `id-token: write` permission | Should not happen on a fresh main — open an issue. |

## Out of scope

- **TestPyPI**. The release candidates pattern (`-rcN`) gives us
  production-equivalent dry runs without needing a separate index.
- **Automated changelog**. The `github-release` job uses GitHub's
  built-in `generate_release_notes` from PR titles; a curated
  CHANGELOG.md is deferred to a later item.
- **Automated version bumps**. The version is bumped by hand because
  the cadence is low (every few weeks at most) and the two-file edit
  is hard to mistype.
