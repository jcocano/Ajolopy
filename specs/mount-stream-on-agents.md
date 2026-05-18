# AJ-87 — Mount `@Stream` on `@Agent` (and `@Workflow`) classes

> Tracked in [`board.json`](../board.json) as `AJ-87`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (framework bug). Milestone: `v0.1`. Priority: `p0`.

## What

`AjolopyFactory.create` only scans `compiled.controllers` for
`@Stream`-marked methods (`src/ajolopy/factory/factory.py:226`):

```python
stream_carriers = [cls for cls in compiled.controllers if any(iter_stream_methods(cls))]
```

A class decorated with `@Agent` (or `@Workflow`) that also declares an
`@Stream("/some-path")` method lives in `compiled.agents` /
`compiled.workflows`, NOT in `compiled.controllers`. The route is
**silently never mounted** on the Starlette HTTP app.

## Why this is a launch-blocker

The docsbot dogfood app (`dogfood/docsbot/`) puts `@Stream("/chat")`
on the `@Agent`-decorated `DocsAgent`. Same pattern is in the killer
demo of the README (`support-agent` example) and is taught in the
tutorial — it is the documented v0.1 idiom. With the bug, **every
deployment of that pattern via bare uvicorn returns 404 on the
streaming endpoint**.

The gap survived this long because `ajolopy dev` wires the routes via
a different path (the CLI bootstraps the app and walks the agent
metadata itself), so local development works. Production deploys via
bare uvicorn (the documented Dockerfile pattern) silently break.

Tests passed throughout because the docsbot's `test_stream_route_is_registered`
only inspects the `@Stream` decorator's metadata on the method, not
whether the route is actually mounted on the live app.

## Fix

Change the stream-carrier collection in `factory.py:226` from:

```python
stream_carriers = [cls for cls in compiled.controllers if any(iter_stream_methods(cls))]
```

to:

```python
stream_carriers = [
    cls
    for cls in (*compiled.controllers, *compiled.agents, *compiled.workflows)
    if any(iter_stream_methods(cls))
]
```

`@Stream` is valid on any of these three primitive classes, so the
mount scan should cover the union.

## Acceptance criteria

- [ ] `factory.py:226` scans agents + workflows + controllers (in
      addition to controllers) for `@Stream` carriers.
- [ ] New regression test in `tests/factory/` that builds an app with
      a single `@Agent` class carrying `@Stream("/x")`, then asserts
      `/x` is in the routing table of the resulting `AjolopyApp.http`.
      The bug repro must be straightforward: without the fix, the
      route is missing; with the fix, the route is present.
- [ ] The existing test suite stays green — no other test relied on
      streams-only-from-controllers semantics.
- [ ] Per the launch-readiness convention, the 7-subprojects smoke
      runs clean against the fix before tagging.

## Out of scope

- Adding a test that actually invokes the `/x` route via the test
  client — the regression we care about is the *routing*, not the SSE
  semantics (covered elsewhere). One assertion on the route table is
  enough to lock in the fix.
- Reworking the controllers/agents/workflows distinction. The fix is
  the smallest possible change that closes the gap.

## Implementation notes

<!-- Filled when this item ships. Record the regression test path, the
final form of the factory line, and any other surfaces (e.g. the
docsbot's own `test_stream_route_is_registered`) that should grow a
"is actually mounted" assertion in a follow-up. -->
