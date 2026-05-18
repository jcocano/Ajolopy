# AJ-93 — Dispatcher auto-loads `.env` so every subcommand sees env vars

> Tracked in [`board.json`](../board.json) as `AJ-93`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (CLI / launch-readiness). Milestone: `v0.1`. Priority: `p0`.

## What

`ajolopy.cli.dispatcher.main` now calls `load_dotenv(cwd=Path.cwd(),
environ=os.environ)` BEFORE invoking the subcommand handler. The
helper is extracted to `src/ajolopy/cli/_dotenv.py` so both the
dispatcher and any individual subcommand can call it (idempotent;
shell env still wins).

## Why

AJ-88 scoped the `.env` autoload to `ajolopy dev` only. The demo
flow's `ajolopy eval --ci` step crashed with
`AgentConfigError: Failed to instantiate provider 'anthropic':
ANTHROPIC_API_KEY missing` because eval re-imports the user's agent
class (which constructs providers) without loading `.env` first. Every
other subcommand that touches user code (`doctor`, `env:show /
validate / diff`, `generate`) had the same gap.

The principle the user surfaced repeatedly during launch prep:
**transparent for devs — the wizard's documented Next steps must work
without workarounds**. AJ-88 fixed one path; AJ-93 fixes the class.

## Approach

Extract the `_load_dotenv` helper from `cli/commands/dev.py` into a
new module `cli/_dotenv.py` (renamed `load_dotenv`, no underscore —
it's now a small public-API helper). Call it from
`dispatcher.main()` right after `parse_args` and before dispatching
to the bound handler.

`cli/commands/dev.py` still calls its own internal copy as a safety
net (idempotent, harmless redundancy). Future cleanup task: dev
should call the shared helper, but the redundancy buys us a known-
green baseline.

## Acceptance criteria

- [x] `cwd/.env` is loaded into `os.environ` before any subcommand
      handler runs.
- [x] Shell-set vars still win over `.env` entries.
- [x] Absence of `.env` is not an error.
- [x] `ajolopy eval --ci` from a fresh scaffolded project root (with
      a valid `.env`) runs end-to-end without `PYTHONPATH=` or
      `export ANTHROPIC_API_KEY=`.
- [x] Regression test in `tests/cli/test_dispatcher_dotenv.py` covers
      all of the above.

## Out of scope

- Cleaning up the duplicate call inside `cli/commands/dev.py`. The
  duplication is intentional in this change to minimise blast radius;
  file a follow-up cleanup if/when it bothers anyone.

## Implementation notes

Helper relocated to `src/ajolopy/cli/_dotenv.py` with a runtime
`Path` import (PEP 649 + the framework's no-`from-__future__-import-
annotations` rule make `if TYPE_CHECKING:` imports unsafe for
annotations that get introspected via `inspect.signature`). 3 new
regression tests in `tests/cli/test_dispatcher_dotenv.py` lock in the
contract. Full suite stays at 1996 passed / 25 skipped + 3 new = 1999.
