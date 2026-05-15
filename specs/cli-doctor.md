# AJ-40 — `ajolopy doctor` system + project + env + connectivity diagnostic

> Tracked in [`board.json`](../board.json) as `AJ-40`. One command that runs ~12
> health checks and prints a clear report. The "lighthouse for AI apps"
> from the Brief.

## What

`ajolopy doctor` runs a fixed list of diagnostic checks in order and
prints `✓` / `✗` / `⚠️ ` per check. Exit 0 when no `✗`. Exit 1
otherwise.

## Public surface (v0.1)

```bash
ajolopy doctor [--ci] [--skip <name>]
```

- `--ci` — JSON output, non-TTY.
- `--skip` — skip a named check (repeatable).

### Checks (v0.1)

| # | Check                       | Pass criterion                                          |
|---|-----------------------------|---------------------------------------------------------|
| 1 | `python_version`            | `sys.version_info >= (3, 14)`                           |
| 2 | `ajolopy_installed`         | `ajolopy` importable.                                   |
| 3 | `venv_present`              | `.venv/` exists in cwd OR `VIRTUAL_ENV` set.            |
| 4 | `pyproject_present`         | `pyproject.toml` in cwd.                                |
| 5 | `project_structure`         | `src/<pkg>/main.py` discoverable.                       |
| 6 | `env_file_present`          | `.env` exists.                                          |
| 7 | `env_validation`            | `ConfigService.load_from_env()` succeeds.               |
| 8 | `anthropic_api_key`         | `ANTHROPIC_API_KEY` set AND `provider.health_check()` returns OK (if `claude-*` model used somewhere). |
| 9 | `openai_api_key`            | Analogous for OpenAI.                                   |
| 10 | `gemini_api_key`           | Analogous for Gemini.                                   |
| 11 | `otel_endpoint`             | If `OTEL_EXPORTER_OTLP_ENDPOINT` set, reachable.        |
| 12 | `mcp_servers`               | If `@MCP` classes declared, each server `connect()` succeeds (best-effort, 5s timeout). |

Each check returns `passed: bool`, `message: str`, `duration_ms: float`.

### Default output

```text
$ ajolopy doctor

📋 Running 12 diagnostic checks...

✓ python_version        Python 3.14.3
✓ ajolopy_installed     version 0.0.1
✓ venv_present          .venv/
✓ pyproject_present     pyproject.toml in cwd
✗ project_structure     src/<pkg>/main.py not found
⚠️  env_file_present    .env not found (using defaults)
✓ env_validation        4 vars OK
✓ anthropic_api_key     reachable
- openai_api_key        skipped (not configured)
- gemini_api_key        skipped (not configured)
⚠️  otel_endpoint        OTEL_EXPORTER_OTLP_ENDPOINT not set
- mcp_servers           skipped (no @MCP classes detected)

Summary: 6 passed, 1 failed, 2 warnings, 3 skipped

Exit code: 1
```

`-` (skipped) when the check isn't applicable. `⚠️ ` for non-fatal
warnings. `✗` for failures (causes exit 1).

### `--ci` JSON

```json
{
  "schema_version": 1,
  "checks": [
    {"name": "python_version", "passed": true, "message": "Python 3.14.3", "duration_ms": 1.2}
  ],
  "passed": 6, "failed": 1, "warnings": 2, "skipped": 3,
  "exit_code": 1
}
```

## Cross-cuts

### AJ-60 (CLI dispatcher) — additive
- Register `doctor` subcommand.

### AJ-12 (ConfigService) — reuse
- For `env_validation`.

### AJ-18+19+20+21+22 (providers) — reuse
- For `*_api_key` checks: call a tiny `provider.health_check()`
  method on each provider class. Add the method to the
  `LLMProvider` ABC if it doesn't already exist
  (probably 1-line addition: `async def health_check(self) -> None:
  raise NotImplementedError`). Each concrete provider implements
  with the cheapest request shape (list models, ping endpoint).

### AJ-7 (`@MCP`) — reuse
- Walks the imported project for `@MCP`-decorated classes; for each,
  tries `registry.connect()` with a short timeout.

## Out of scope

- Auto-fixing detected problems → v0.2.
- `ajolopy doctor --watch` (continuous) → v0.2.
- Disk / memory / CPU checks → v0.2.
- Network latency benchmarks → v0.2.

## Acceptance criteria

- [ ] Each of the 12 checks runs in order and reports
      `passed/failed/warning/skipped`.
- [ ] All-pass → exit 0.
- [ ] Any fail → exit 1.
- [ ] Warnings don't trigger exit 1.
- [ ] `--ci` JSON matches schema.
- [ ] `--skip python_version` skips that check (still appears as
      `skipped`).
- [ ] Provider health checks gracefully degrade when network is
      unavailable (treat as warning, not failure).
- [ ] MCP server check uses a 5s timeout per server.
- [ ] Total run completes in <30s even with all checks engaged.

## Implementation pointers

- `src/ajolopy/cli/commands/doctor.py` — single file with check
  classes + runner + renderer.
- Each check is a small class with `name`, `run() -> CheckResult`.
- Tests: `tests/cli/doctor/`.
- Add `LLMProvider.health_check()` if missing (in
  `src/ajolopy/providers/base.py`); implement on each concrete
  provider with a cheap network call.

## Implementation notes

(Empty — populated by the implementation PR.)
