# AJ-36 — `ajolopy env:show / validate / diff`

> Tracked in [`board.json`](../board.json) as `AJ-36`. CLI surface over AJ-12's
> `ConfigService`. Three sibling subcommands for inspecting and
> validating the `.env` configuration.

## What

Three subcommands under the `env` namespace:

| Command            | Purpose                                                       |
|--------------------|---------------------------------------------------------------|
| `ajolopy env:show` | List every env var the app reads + whether it's set + length. |
| `ajolopy env:validate` | Run AJ-12's Pydantic validation; report per-var pass/fail. |
| `ajolopy env:diff` | Compare `.env` vs `.env.example`; show adds / removes / changes. |

## Public surface (v0.1)

```bash
ajolopy env:show     [--ci]
ajolopy env:validate [--ci]
ajolopy env:diff     [--ci]
```

- All three accept `--ci` for JSON output to stdout (non-TTY).

### `env:show` output

```text
$ ajolopy env:show

ANTHROPIC_API_KEY  ✓ set      (sk-…32 chars)
OPENAI_API_KEY     ✗ missing
APP_ENV            ✓ set      (production)
LOG_LEVEL          ✓ set      (info)
```

Reads the variable names from the discovered `BaseConfig` subclass
(AJ-12). Values that look secret (key, token, password, secret in the
name) are masked: only first 3 + last 4 chars + length.

### `env:validate` output

```text
$ ajolopy env:validate

✓ ANTHROPIC_API_KEY  valid
✗ OPENAI_API_KEY     required, missing
✓ APP_ENV            valid
✗ LOG_LEVEL          must be one of: debug, info, warn, error  (got: trace)

2 valid, 2 invalid
Exit code: 1
```

Exit 0 when all pass; 1 when any fail.

### `env:diff` output

```text
$ ajolopy env:diff

In .env but NOT .env.example:
  + INTERNAL_DEBUG_TOKEN

In .env.example but NOT .env:
  - OPENAI_API_KEY
  - REDIS_URL
```

Reads both files from cwd. Missing `.env.example` → error message + exit 1.

### `--ci` JSON

```json
{
  "schema_version": 1,
  "subcommand": "env:show",
  "vars": [{"name": "...", "set": true, "length": 32, "masked_value": "sk-…abcd"}],
  "exit_code": 0
}
```

Per-subcommand shape; documented inline.

## Cross-cuts

### AJ-60 (CLI dispatcher) — additive
- Register the three subcommands. Argparse colons-in-names need
  escaping; use `env-show` / `env-validate` / `env-diff` as the
  parser names BUT alias to the colon form via a thin wrapper in
  `dispatcher.py`. (argparse subparsers don't accept `:` in command
  names directly.)

### AJ-12 (ConfigService) — reuse
- `env:show` reads the discovered `BaseConfig` subclass + introspects
  its `Field` definitions.
- `env:validate` runs `ConfigService.load_from_env()` and catches
  `ValidationError`, reports per-field.

## Out of scope

- `env:set` / `env:unset` write operations → v0.2.
- `.env.local` / multi-file env support → v0.2.
- Secrets manager integration → v0.2.

## Acceptance criteria

### `env:show`
- [ ] Lists every field of the discovered `BaseConfig` subclass.
- [ ] Sets `✓` when env var is present, `✗` otherwise.
- [ ] Masks values for secret-looking names.
- [ ] `--ci` JSON output.

### `env:validate`
- [ ] All valid → exit 0.
- [ ] Any invalid → exit 1.
- [ ] Per-field error message included.
- [ ] `--ci` JSON output.

### `env:diff`
- [ ] Reads `.env` and `.env.example` from cwd.
- [ ] Lists adds and removes.
- [ ] Missing `.env.example` → exit 1 with message.
- [ ] Identical files → exit 0 with "no differences" message.

### CLI integration
- [ ] All 3 subcommands registered.
- [ ] Argparse uses `env-show` etc. internally; user-facing examples
      and `--help` show the colon form via parser description.

## Implementation pointers

- `src/ajolopy/cli/commands/env.py` — single file with the 3
  subcommand handlers and shared helpers.
- Register via `dispatcher.py` — add a thin alias map so
  `argv[0] == "env:show"` rewrites to `["env-show", ...]` before
  argparse sees it.
- Tests: `tests/cli/env/`.

## Implementation notes

(Empty — populated by the implementation PR.)
