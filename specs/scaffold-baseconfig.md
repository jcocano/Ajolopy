# AJ-94 — Scaffold emits a `BaseConfig` subclass so `doctor` + `env:*` work on fresh install

> Tracked in [`board.json`](../board.json) as `AJ-94`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (CLI templates / launch-readiness). Milestone: `v0.1`.
> Priority: `p0`.

## What

`src/ajolopy/cli/commands/_templates/new/base/` now emits a new
`src/<package>/config.py` template that declares an `AppConfig`
subclass of `ajolopy.config.BaseConfig` with typed fields for every
variable the generated `.env.example` ships. The root `@Module` in
`app_module.py.tmpl` registers the subclass via `providers=[AppConfig]`
so the `ajolopy env:*` discovery path can locate it.

Per-provider fields are driven by the same `_PROVIDER_DEFAULTS` /
`_UNIVERSAL_PREFIX_DEFAULTS` tables that already power the
`.env.example` and `support.py` template substitutions, so the wizard's
single source of truth keeps matching.

## Why

Today the scaffold's `.env.example` includes `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / etc., `APP_ENV`, and `LOG_LEVEL`, but the project
never declares a `BaseConfig` subclass. Two CLI commands break on
every fresh install:

- `ajolopy doctor` — the framework's bare `BaseConfig` is
  `model_config = {"extra": "forbid"}` and the `EnvValidationCheck`
  instantiates it against the cwd. The check rejects every key in
  `.env` as `extra_forbidden` and reports `env_validation FAIL`.
- `ajolopy env:show` and `ajolopy env:validate` — both rely on
  `_discover_config()` (see `src/ajolopy/cli/commands/env.py`), which
  walks `src/<package>/app_module.py` for the first `BaseConfig`
  subclass. With no subclass declared, the commands print
  `"no BaseConfig subclass found in '<pkg>.app_module'"` and exit
  with the discovery exit code — they are 100% unusable on every
  fresh scaffold.

The fix is the same pattern used by every framework that ships a
typed config layer (NestJS `ConfigModule`, Rails `Rails.application.config`):
the scaffold emits the file that declares the typed view, the user
edits it as their config grows. The default mágico is the four-field
`AppConfig` covering exactly the keys the scaffold's own
`.env.example` writes; the escape hatch is the user subclassing /
extending `AppConfig` as their project grows.

## Acceptance criteria

- [ ] Scaffold writes `src/<package>/config.py` with an `AppConfig`
      subclass of `ajolopy.config.BaseConfig`.
- [ ] `AppConfig` declares one field per `.env.example` key for the
      chosen provider (`anthropic_api_key`, `openai_api_key`,
      `google_api_key`, or the matching universal prefix's key /
      base URL) plus `app_env` and `log_level`.
- [ ] `app_module.py.tmpl` imports `AppConfig` and registers it via
      `providers=[AppConfig]` on the root `@Module`.
- [ ] Generated project's `ajolopy env:show` lists every declared
      field instead of crashing with the discovery error.
- [ ] Generated project's `ajolopy env:validate` exits `0` when a
      well-formed `.env` is present.
- [ ] `ajolopy doctor` against the generated project no longer
      reports `env_validation FAIL` with `extra_forbidden`.
- [ ] Regression test in `tests/cli/new/` covers the four provider
      variants (anthropic / openai / gemini / universal:ollama) and
      asserts the AppConfig file exists, imports BaseConfig, and
      declares the expected fields.

## Out of scope

- Updating the framework's own bare `BaseConfig` (still
  `extra=forbid`; users opting out subclass with `extra="ignore"`).
- Multi-tenancy / RBAC config layers (post-v0.1).

## Doctor-side change (paired with the scaffold fix)

`EnvValidationCheck` (in `src/ajolopy/cli/commands/doctor.py`) now
prefers the project's `BaseConfig` subclass via the same
`_discover_config` walk `env:*` already uses. When no project
subclass exists AND the cwd's `.env` has at least one key, the check
surfaces a warning ("declare a project-level subclass") instead of
hard-failing — the bare `BaseConfig` (`extra=forbid`) would otherwise
reject every key on the next user's machine even after their `cp
.env.example .env`, turning the doctor into a false-positive machine
on every fresh install.

## Implementation notes

<!-- Filled when this item ships. Record the smoke verification + the
tests added beyond the existing scaffold assertions. -->
