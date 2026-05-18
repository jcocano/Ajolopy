# AJ-91 — `ajolopy dev` should pass `factory=True` to uvicorn when target is a coroutine

> Tracked in [`board.json`](../board.json) as `AJ-91`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (CLI bug). Milestone: `v0.1`. Priority: `p1`.

## What

`ajolopy dev` boots uvicorn against the project's ASGI target (auto-detected
as `src/<package>/main.py:app` or supplied via `--app module:var`). The
scaffold + every example expose `app` as a **zero-arg async coroutine
factory** that returns the built `AjolopyApp`:

```python
async def app() -> object:
    return await AjolopyFactory.create(AppModule)
```

uvicorn supports this pattern, but only emits the warning

```
WARNING: ASGI app factory detected. Using it, but please consider
setting the --factory flag explicitly.
```

on every boot, because the dev command never passes `factory=True` (Python
API) / `--factory` (subprocess) to uvicorn. The warning is harmless but
shouts on every fresh dev run, including the launch demo video.

## Why

Cosmetic but visible. The warning:

- appears in the first 10 lines of every `ajolopy dev` output,
- shows up in the launch screencast,
- makes the framework look misconfigured to a first-time user evaluating
  Ajolopy against Mastra / FastAPI,
- is trivial to fix at the source (uvicorn already detects this case
  reliably with `inspect.iscoroutinefunction`).

Fixing it is launch-readiness hygiene.

## Acceptance criteria

- [x] `_build_config` (or its caller) detects whether the resolved
      attribute is a coroutine function vs. a plain ASGI app, and passes
      `factory=True` to `uvicorn.Config(...)` in the coroutine case.
- [x] Detection uses `inspect.iscoroutinefunction(target)` — the standard
      signal. A pre-built ASGI app (a plain callable taking
      `scope/receive/send`, not a coroutine function) keeps the existing
      `factory=False` default.
- [x] Detection happens **after** the target is resolved (after import)
      so it works for both `--app` and auto-detect paths.
- [x] Regression test (`tests/cli/dev/test_factory_flag.py`) asserts:
      - coroutine-typed `app` → produced `uvicorn.Config.factory is True`,
      - plain-callable `app` (ASGI3 stub) → produced
        `uvicorn.Config.factory is False`.
- [x] `uv run ruff check && uv run ruff format --check` clean.
- [x] `uv run pyright` clean.
- [x] `uv run pytest tests/cli/dev/` green (and full suite).
