# AJ-88 — `ajolopy dev` auto-loads `.env` from cwd at startup

> Tracked in [`board.json`](../board.json) as `AJ-88`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (CLI / Brief v4.0 requirement). Milestone: `v0.1`.
> Priority: `p0`.

## What

`ajolopy dev` now reads `cwd/.env` and populates `os.environ` with the
keys it declares **before** importing the user's app module. Shell-set
env vars win over `.env` entries (matches `pydantic-settings` /
`docker compose` precedence).

## Why

Brief v4.0 calls out `.env validado al arrancar` as a v0.1
non-negotiable. The wizard's printed `Next steps` instructs
`cp .env.example .env` then `ajolopy dev`, but prior to this fix the
dev command did not source the file, so providers that read API keys
directly (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`)
crashed at user-module import time with "API key missing". Wizard
documentation was lying.

## Approach

A pure `_load_dotenv(cwd, environ)` helper in
`src/ajolopy/cli/commands/dev.py`, called as the first step of
`_command`. Uses `python-dotenv` (already a transitive dep via
`pydantic-settings>=2.14.1`, zero new install footprint) so parser
semantics match the `BaseConfig` loader. Only reads `cwd/.env`, no
parent-directory walk. Idempotent.

## Acceptance criteria

- [x] `cwd/.env` is loaded into `os.environ` before
      `importlib.import_module` of the user module.
- [x] Shell-set vars take precedence over `.env` entries.
- [x] Bare `KEY=` in `.env` does not clobber a shell-set value for the
      same key.
- [x] No-`.env` case continues silently.
- [x] Regression test in `tests/cli/dev/test_dotenv.py` covers all of
      the above + an end-to-end test that the user-module import sees
      the loaded vars.

## Implementation notes

Shipped in PR #151, commit `cc5745f`. 8 regression tests added. Smoke
verified against a fresh `ajolopy new acme && cd acme && cp .env.example
.env && ajolopy dev` — boots without `ANTHROPIC_API_KEY missing`.
