# AJ-80 — Eager-register built-in providers on package import

> Tracked in [`board.json`](../board.json) as `AJ-80`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (CLI / runtime). Milestone: `v0.1`. Priority: `p0`.

## What

A fresh `pip install ajolopy==0.1.3` + `ajolopy new myapp` +
`ajolopy dev` crashed at boot with
`ProviderNotRegisteredError: No provider registered for key 'anthropic'.
Known keys: []`. Each built-in provider subpackage registers itself as
an import-time side effect, but `from ajolopy import Agent, ...` never
imported those subpackages, so the registry stayed empty and the
scaffold default (`@Agent(model="claude-opus-4-7", ...)`) blew up.

## Fix

`src/ajolopy/providers/__init__.py` now eagerly imports the four v0.1
provider subpackages (anthropic, openai, gemini, universal_openai), so
the registry is populated as soon as `ajolopy` is imported. SDKs are
already runtime deps in `pyproject.toml`, so the install footprint
does not change. The mcp consumer provider stays lazy because it sits
behind an optional extra.

## Acceptance criteria

- [x] `from ajolopy import Agent` populates the provider registry for
      `anthropic`, `openai`, `gemini`, `universal`.
- [x] `tests/providers/test_auto_registration.py` spawns a fresh
      interpreter and asserts the registry is populated without
      explicit subpackage imports.
- [x] Smoke validation: `pip install -e .` in a clean venv, then
      `python -c "from ajolopy import Agent; @Agent(model='claude-opus-4-7', ...)"`
      no longer raises `ProviderNotRegisteredError`.

## Shipped

PR #143 — commit `40fc78d` — released in `v0.1.4`.
