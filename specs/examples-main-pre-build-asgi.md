# AJ-99 — Examples `main.py` uses async factory pattern (uvicorn cannot await)

> Tracked in [`board.json`](../board.json) as `AJ-99`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (launch-surface examples). Milestone: `v0.1`.
> Priority: `p0`.

## What

Every example under `examples/` ships a `main.py` declaring a zero-arg
coroutine `async def app() -> object` and returns
`await AjolopyFactory.create(AppModule)` from it. Migrate each example
to the pre-built-at-import pattern that the dogfood docsbot (PR #149)
and the scaffold template (AJ-92, PR #156) already use: keep
`build_app()` as the async factory, then bind
`ajolopy_app: AjolopyApp = asyncio.run(build_app())` at module import
and expose `app = ajolopy_app.http` (the inner Starlette ASGI3
callable).

Affected files:

- `examples/support-agent/src/support_agent/main.py`
- `examples/oncall-agent/src/oncall_agent/main.py`
- `examples/contextual-rag/src/contextual_rag/main.py`
- `examples/local-ollama/src/local_ollama/main.py`
- `examples/memory-assistant/src/memory_assistant/main.py`
- `examples/web-research/src/web_research/main.py`

`dogfood/docsbot/src/docsbot/main.py` already ships the correct
pattern (PR #149) and is explicitly out of scope.

## Why

Uvicorn 0.47's `factory=True` mode (which `ajolopy dev` sets after
AJ-91) **does not await async factories** — it calls the factory
synchronously, treats the returned coroutine as the ASGI app, and the
asgi2 middleware then crashes with
`TypeError: 'coroutine' object is not callable`. Every HTTP request
against an example returns 500.

AJ-92 fixed the scaffold template emitted by `ajolopy new` so future
projects ship the pre-built pattern. The examples in `examples/`
predate AJ-92, were never migrated, and are the primary launch-surface
artefacts a visitor copy-pastes from. This sweep propagates the AJ-92
pattern to all six remaining examples so every documented quickstart
target works against uvicorn out of the box.

## Acceptance criteria

- [ ] All six affected example `main.py` files expose `app` as the
      pre-built Starlette ASGI3 callable (`ajolopy_app.http`), not a
      coroutine factory.
- [ ] `ajolopy_app: AjolopyApp = asyncio.run(build_app())` runs at
      module import time; `build_app()` remains available as the async
      factory for tests / advanced wiring.
- [ ] `main()` becomes a synchronous no-op wrapper — the ASGI app is
      already constructed at import, so the `__main__` entry point only
      exists to keep `python -m <package>.main` valid.
- [ ] `curl -sw "\nstatus=%{http_code}\n" -X POST
      localhost:8000/chat -d '{"message":"hi"}'` against
      `ajolopy dev` of at least one affected example returns
      `status=200` (SSE error event from a fake API key is acceptable),
      NOT `status=500`.
- [ ] `uv run ruff check && uv run ruff format --check` passes.
- [ ] `uv run pyright` passes.
- [ ] `uv run pytest` passes (framework suite).
- [ ] `uv run pytest` passes in each affected example directory.

## Out of scope

- Touching `dogfood/docsbot/src/docsbot/main.py` (already shipped in
  PR #149 with the pattern this sweep propagates).
- Touching the scaffold template (already shipped in AJ-92 / PR #156).
- Touching `ajolopy dev`'s `_is_factory_target` detection (AJ-91); the
  examples now expose `app` as a regular ASGI3 callable, which `dev`
  handles without any factory hint.

## Implementation notes

<!-- Filled when this item ships. Record the smoke verification (curl
output against `ajolopy dev` of at least one affected example) + any
tests added beyond the existing assertions. -->
