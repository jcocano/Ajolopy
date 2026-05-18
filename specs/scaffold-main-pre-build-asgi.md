# AJ-92 — Scaffold `main.py` pre-builds the ASGI app at import time

> Tracked in [`board.json`](../board.json) as `AJ-92`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (CLI templates / launch-readiness). Milestone: `v0.1`.
> Priority: `p0`.

## What

`src/ajolopy/cli/commands/_templates/new/base/src/__package__/main.py.tmpl`
now pre-builds the ASGI app at import time via `asyncio.run(build_app())`
and exposes the inner Starlette callable as `app`. The previous
template shipped a zero-arg coroutine `async def app() -> object` and
relied on the server to await it.

## Why

Uvicorn's `factory=True` mode (which AJ-91 made `ajolopy dev` set
correctly) **does not await async factories** in v0.47 — it calls the
factory synchronously and treats the returned coroutine as the ASGI
app. The asgi2 middleware then tries `app(scope)`, gets
`TypeError: 'coroutine' object is not callable`, and returns 500 on
every request.

This is the same gap the docsbot hit during its first public deploy
(closed in PR #149). The framework templates were never updated, so
every visitor following `ajolopy new` + the wizard's documented Next
steps produced a scaffold that crashed on the very first `curl /chat`.

The previous shape "intentionally import-clean: no factory bootstrap
at import time" was a goal that turned out to be incompatible with
uvicorn's actual factory semantics. Pre-building at import is the
pattern every other ASGI app uses (FastAPI, Starlette examples) and
is what production hosting expects.

## Acceptance criteria

- [ ] Scaffold template exposes `app` as a pre-built Starlette ASGI3
      callable (not a coroutine factory).
- [ ] `ajolopy_app: AjolopyApp = asyncio.run(build_app())` runs at
      module import; `build_app()` remains available as the async
      factory for tests / advanced wiring.
- [ ] `curl -N -X POST localhost:8000/chat -d '{"message":"hi"}'`
      against `ajolopy dev` of a fresh scaffold returns SSE chunks
      (or the LLM provider's error if no API key), NOT
      `TypeError: 'coroutine' object is not callable`.
- [ ] Existing `tests/cli/new/` suite (including the
      `test_main_references_app_module` assertion) keeps passing.
- [ ] No public API change: the template still imports `AjolopyFactory`
      and `AppModule` the same way; only the shape of `app` changes.

## Out of scope

- Touching `ajolopy dev`'s `_is_factory_target` detection (AJ-91).
  That fix is still correct for users who hand-write an async factory.
- Touching the docsbot's `main.py` (already shipped in PR #149 with
  the same pattern).

## Implementation notes

<!-- Filled when this item ships. Record the smoke verification (curl
output against a fresh scaffold) + any tests added beyond the
existing assertions. -->
