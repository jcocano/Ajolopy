# AJ-33 — `ajolopy dev` dev server with reload

> Tracked in [`board.json`](../board.json) as `AJ-33`. Wraps `uvicorn --reload`
> with .env hot-reload for fast iteration. The dev counterpart to
> `ajolopy new` (AJ-32).

## What

`ajolopy dev` is a CLI subcommand that:

1. **Auto-detects** the entry point via the AJ-32 convention:
   `src/<package>/main.py:app`. Override with `--app <module>:<var>`.
2. **Starts uvicorn** programmatically with `--reload`. Watches
   `src/` + `.env` by default; `--watch <path>` adds extra dirs.
3. **Reloads on `.env` change** by re-validating the env (best-effort
   via uvicorn's file watcher; full re-bootstrap is not in v0.1).
4. **Prints connection info** when ready: URL, watched paths,
   reload behavior.

## Why

Brief v4.0 §"7 dolores ancla" implicitly: the Series A AI Engineer
runs `python -m uvicorn app:app --reload` 50 times a day. `ajolopy
dev` collapses that to one command with built-in `.env` handling and
sensible defaults.

## Public surface (v0.1)

```bash
$ ajolopy dev

📡 Starting Ajolopy dev server...
   App:     my_agent.main:app
   URL:     http://127.0.0.1:8000
   Watching: src/, .env
   Reload:  on

INFO:     Application startup complete.
```

### CLI signature

```
ajolopy dev [--app <module>:<var>]
            [--host <host>]
            [--port <port>]
            [--watch <path>]
            [--no-reload]
```

- `--app` — explicit `module:var` (default: auto-detect).
- `--host` — bind host (default `127.0.0.1`).
- `--port` — bind port (default `8000`).
- `--watch` — additional dir to watch for reload; repeatable.
- `--no-reload` — disable reload (useful for debugging the framework
  itself).

### Auto-detection algorithm

1. Look for `src/` in `os.getcwd()`. If absent → exit 1 with hint
   ("--app required, or run from a project root").
2. List subdirectories of `src/` excluding `__pycache__`. There must
   be EXACTLY ONE package directory (i.e., one subdir containing
   `__init__.py`). Else → exit 1 with hint listing what was found.
3. Look for `src/<package>/main.py`. If absent → exit 1.
4. Verify the module imports cleanly AND defines an `app` attribute.
   Import errors → exit 1 with the original traceback. Missing `app`
   → exit 1 with hint.
5. Return `(<package>.main, "app")`.

### `--app` override

Accepted forms (mirrors `mcp-serve`):
- `my_pkg.main:app` — module path + variable name.
- `my_pkg.submodule:my_asgi_app` — any module:var combo.

Exit 1 if module / attribute not found.

### Watched paths

- `src/` — default when auto-detection succeeded; OR the parent dir
  of the imported module's file when `--app` was used.
- `.env` — always added if it exists in cwd.
- `--watch <path>` — add extra paths (repeatable).

uvicorn's `reload_dirs=[...]` is set to the watched paths. The
`.env` file is watched by adding its PARENT directory to
`reload_dirs` AND filtering with `reload_includes=["**/.env",
"*.py"]` so unrelated file changes in the parent don't trigger.

### Output

```text
📡 Starting Ajolopy dev server...
   App:     {module}:{var}
   URL:     http://{host}:{port}
   Watching: {dirs}
   Reload:  on

<uvicorn output follows>
```

On non-TTY stdout, skip emoji + colors.

### Lifecycle

- `Ctrl+C` → uvicorn handles SIGINT, prints "Shutting down" once,
  exits 0.
- Reload on file change: uvicorn re-imports the module. The new
  `AjolopyApp` is built fresh. If the new code raises at import
  time, uvicorn logs the error and KEEPS the old app running
  (uvicorn default behavior).

### `.env` changes

In v0.1, an `.env` save triggers uvicorn's reload (because we add
the dir + filter). The reload re-imports the user's module, which
runs `AjolopyFactory.create(...)` again, which re-reads `.env` via
`ConfigService` (AJ-12). End-to-end `.env` changes ARE picked up,
just via the reload pathway. v0.2 may add a more granular
`AjolopyApp.reload_config()` hook.

## Cross-cuts

### AJ-60 (CLI dispatcher) — additive
- Register `dev` subcommand in
  `src/ajolopy/cli/commands/__init__.py::register_subcommands`.

### Runtime deps — additive
- `uvicorn` is ALREADY a dep of `starlette` (AJ-15's HTTP layer).
  No new dep here. AJ-33 imports `uvicorn` programmatically.

## Out of scope

- **Granular `.env` re-validation without process reload** — v0.2.
- **HTTPS / TLS support** — uvicorn supports it but the dev command
  defaults to plain HTTP. v0.2 may add `--ssl-cert` / `--ssl-key`.
- **Multi-process dev** (uvicorn workers) — single-process only.
- **Browser auto-open** — defer to v0.2; `--no-open` would be the
  knob.
- **Custom log format** — uvicorn's default. v0.2.

## Acceptance criteria

### Auto-detection
- [ ] In a tmp_path with `src/myapp/main.py` defining `app =
      object()`, `ajolopy dev --no-reload --port 0` resolves to
      `myapp.main:app`.
- [ ] No `src/` dir → exit 1.
- [ ] Two packages under `src/` → exit 1.
- [ ] `src/myapp/main.py` missing `app` → exit 1.

### `--app` override
- [ ] `ajolopy dev --app myapp.main:app` works without auto-detect.
- [ ] `--app no.such.module:app` → exit 1.
- [ ] `--app myapp.main:no_such_var` → exit 1.

### Flags
- [ ] `--host 0.0.0.0` is forwarded to uvicorn.
- [ ] `--port 8080` is forwarded.
- [ ] `--no-reload` disables reload (verified by inspecting the
      uvicorn config the CLI builds).
- [ ] `--watch /tmp/x` is added to `reload_dirs`.

### Output
- [ ] Banner with App / URL / Watching / Reload lines printed
      before uvicorn output.
- [ ] Non-TTY output skips emoji / colors.

### Lifecycle
- [ ] `Ctrl+C` propagation works (verified by sending SIGINT to
      the uvicorn server in a test fixture and asserting clean
      shutdown).

### Smoke test
- [ ] Starts uvicorn in a background thread, exercises a request
      to `/` (or whatever the auto-detected app serves),
      shuts down cleanly. (Use uvicorn's
      `uvicorn.Server.serve()` programmatic API rather than
      `uvicorn.run()` to keep tests in-process.)

## Implementation pointers

- `src/ajolopy/cli/commands/dev.py` — argparse + auto-detection +
  uvicorn integration. ~200 LoC.
- `src/ajolopy/cli/commands/__init__.py` — register `dev.register(sub)`.
- Use `uvicorn.Config(...)` + `uvicorn.Server(...).run()` /
  `serve()`. The programmatic API is preferred over
  `uvicorn.run(...)` so we control the asyncio loop policy.
- Tests: `tests/cli/dev/`.
  - `test_autodetect.py` — every detection branch.
  - `test_app_override.py` — `--app` resolution.
  - `test_flags.py` — host/port/watch/no-reload forwarded into
    `uvicorn.Config`.
  - `test_smoke.py` — programmatic server boot + shutdown.

## Implementation notes

(Empty — populated by the implementation PR.)
