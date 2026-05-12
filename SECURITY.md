# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.0.x | ✅ (pre-alpha, active development) |

Once v0.1 ships, supported versions will be tracked here. Older minors stop
receiving fixes when a newer minor is released.

## Reporting a vulnerability

**Do not** open public GitHub Issues for security vulnerabilities. Email reports
privately to **jesus.cocano@gmail.com** with subject prefix `[ajolopy security]`
and include:

- A description of the issue and its potential impact.
- Steps to reproduce (or a proof-of-concept).
- Affected version(s).
- Any suggested mitigation.

Expect an initial response within **5 business days**. We aim to deliver a fix
within **30 days** for critical issues, longer for low-severity ones.
Coordinated disclosure is preferred — we will work with you on a timeline.

## Security posture

These baselines are enforced by CI from the harness setup forward. They can be
verified by inspecting the workflows under `.github/workflows/`.

### Supply chain

- `uv.lock` is committed and CI runs `uv sync --frozen` — dependencies cannot
  drift mid-PR.
- All GitHub Actions are pinned to commit SHAs (not floating tags).
  [Dependabot](./.github/dependabot.yml) keeps them updated weekly.
- **OSV-Scanner** runs in CI on every PR and weekly. CVEs in transitive deps
  break the build.
- **CodeQL** analyzes Python source on every PR, every push to `main`, and on a
  weekly schedule.
- **OSSF Scorecard** runs weekly and publishes results.

### Secrets

- `.env`, `.env.*` ignored by `.gitignore`.
- [`gitleaks`](https://github.com/gitleaks/gitleaks) runs as a pre-commit hook
  on every commit to catch accidentally committed secrets locally.
- GitHub secret scanning is enabled by default for public repositories.

### Least privilege

- Every CI workflow declares a top-level `permissions: contents: read`.
- Jobs that need elevated permissions (publishing, SARIF upload) declare only
  the specific scope they require.
- The release workflow uses **PyPI trusted publishing (OIDC)** — no long-lived
  tokens live in repository secrets.

### Static analysis

- `ruff` with the `S` (flake8-bandit) ruleset on every PR.
- `pyright` in `strict` mode on every PR.

## Branch protection (required when the repository becomes public)

When this repository is made public, the following `main` branch protections
must be enabled in GitHub repository settings:

- Require a pull request before merging.
- Require status checks to pass: `board`, `lint`, `typecheck`, `test`,
  `osv-scanner`, `codeql`.
- Require **linear history** (no merge commits — rebase or squash).
- Require **signed commits**.
- Disallow force pushes.
- Disallow branch deletion.
- Restrict who can dismiss reviews.

Until the repository is public, these are advisory — local discipline applies.

## Signed commits

Commits to `main` must be cryptographically signed once branch protection is
on. SSH signing is recommended over GPG (simpler, same trust model).

One-time local setup:

```bash
# Pick the SSH key you want to sign with (Ed25519 recommended).
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

Then on GitHub: **Settings → SSH and GPG keys → New SSH key → Key type:
Signing Key** and upload the same public key.

Verify:

```bash
git commit --allow-empty -m "test signing"
git log --show-signature -1
```

You should see `Good "git" signature for ...`.

## Releasing — PyPI Trusted Publisher (OIDC)

Releases publish to PyPI via GitHub OIDC — no long-lived API tokens live in the
repository or in CI.

One-time setup on PyPI (the first time `ajolopy` is reserved):

1. Create the project on PyPI: <https://pypi.org/manage/account/publishing/>.
2. Add a **Trusted Publisher**:
   - Owner: `jcocano`
   - Repository: `ajolopy`
   - Workflow file: `release.yml`
   - Environment: leave empty (or set up a `pypi` GitHub Environment for
     additional review gates).

After that, a tag push (`git tag v0.1.0 && git push --tags`) triggers the
release workflow, which:

1. Builds with `uv build`.
2. Publishes via `pypa/gh-action-pypi-publish` using the OIDC token.

The workflow contains no secrets and is auditable in `.github/workflows/release.yml`.

## Adding a new dependency

Adding any new dependency (runtime or dev) requires:

1. **Justification** in the PR description: which feature needs it, why no
   alternative.
2. **License compatible with MIT** (MIT, Apache-2.0, BSD, ISC). Copyleft
   dependencies require explicit approval.
3. **Active maintenance**: at least one commit in the last 12 months and no
   known critical CVEs against the pinned version.
4. **Pinned in `uv.lock`** via `uv add`. Never hand-edit `pyproject.toml` for
   deps.

## Out of scope

- Cryptography review of the framework's runtime behavior (the framework
  itself does not implement cryptographic primitives in v0.1).
- Hardening of third-party LLM provider responses — agents constructed with
  this framework treat provider output as untrusted by design; document
  guardrails in the relevant primitive's spec.
