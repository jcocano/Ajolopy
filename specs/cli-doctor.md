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

- [x] Each of the 12 checks runs in order and reports
      `passed/failed/warning/skipped`.
- [x] All-pass → exit 0.
- [x] Any fail → exit 1.
- [x] Warnings don't trigger exit 1.
- [x] `--ci` JSON matches schema.
- [x] `--skip python_version` skips that check (still appears as
      `skipped`).
- [x] Provider health checks gracefully degrade when network is
      unavailable (treat as warning, not failure).
- [x] MCP server check uses a 5s timeout per server.
- [x] Total run completes in <30s even with all checks engaged.

## Implementation pointers

- `src/ajolopy/cli/commands/doctor.py` — single file with check
  classes + runner + renderer.
- Each check is a small class with `name`, `run() -> CheckResult`.
- Tests: `tests/cli/doctor/`.
- Add `LLMProvider.health_check()` if missing (in
  `src/ajolopy/providers/base.py`); implement on each concrete
  provider with a cheap network call.

## Implementation notes

- Single-file implementation in `src/ajolopy/cli/commands/doctor.py`.
  Each check is a small class with `name: str` + `async def run() ->
  tuple[bool | None, str]`. Tri-state outcome: `True` = pass, `False`
  = fail, `None` = warn or skip (the runner reads the message prefix
  to disambiguate — messages starting with `"skipped"` are skips,
  every other `None` outcome is a warning).
- `LLMProvider.health_check()` lives on the ABC with a default that
  raises `NotImplementedError`. Each concrete provider (Anthropic,
  OpenAI, Gemini) overrides it with the cheapest network call
  (`models.list(limit=1)` for Anthropic, `models.list()` for OpenAI,
  one-page iteration over `client.aio.models.list()` for Gemini), and
  wraps SDK exceptions in the provider's own `*ProviderError` so the
  doctor never sees raw `httpx` internals. The universal-OpenAI
  adapter inherits the default since its multi-prefix shape doesn't
  map to a single endpoint.
- Provider check downgrade rule: missing env var → `skip`, constructor
  raises → `fail`, network/timeout error from `health_check()` → `warn`.
  This keeps CI green when an upstream is degraded but still catches
  structural problems (wrong key shape, missing SDK).
- OTel check is a short TCP `socket.create_connection`; no exporter SDK
  required so the check stays installable even without the `otel` extra.
- MCP check walks the process-wide `MCPRegistry.registered_classes()`
  and calls `connect_all_for(cls)` with a 5s timeout per class.
- Renderer split: `_render_tty` (emoji on real TTYs, ASCII `[OK]` /
  `[FAIL]` / `[WARN]` / `[SKIP]` brackets when `_is_tty` returns False)
  vs `_render_ci` (deterministic JSON with `schema_version: 1`).
- Tests: `tests/cli/doctor/` with 64 cases across
  `test_individual_checks.py`, `test_runner.py`, `test_output.py`. All
  network calls are mocked (`AsyncMock`/`MagicMock` against the SDK
  clients + monkeypatched `socket.create_connection`); pytest is
  hermetic — no live HTTP, no real SDK calls.
