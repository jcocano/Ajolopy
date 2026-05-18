# AJ-98 — Examples crash at boot — `AsyncGenerator` annotation under `TYPE_CHECKING`

> Tracked in [`board.json`](../board.json) as `AJ-98`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (launch-surface examples). Milestone: `v0.1`.
> Priority: `p0`.

## What

Every example under `examples/` (and historically the dogfood docsbot
before PR #149) declares `from collections.abc import AsyncGenerator`
inside an `if TYPE_CHECKING:` block while using `AsyncGenerator[...]`
as the runtime return annotation on a `@Stream`-decorated handler.
Move the import to the module-level imports with `# noqa: TC003` and
the canonical "must be runtime-visible" comment, matching the docsbot
fix from PR #149 and the scaffold fixes from AJ-92 / AJ-95.

Affected files:

- `examples/support-agent/src/support_agent/agents/team.py`
- `examples/support-agent/src/support_agent/agents/support.py`
- `examples/oncall-agent/src/oncall_agent/agents/oncall.py`
- `examples/contextual-rag/src/contextual_rag/agents/researcher.py`
- `examples/local-ollama/src/local_ollama/agents/reviewer.py`
- `examples/memory-assistant/src/memory_assistant/agents/tracker.py`
- `examples/web-research/src/web_research/agents/researcher.py`

## Why

Python 3.14 + PEP 649 defers annotation evaluation until something
calls `typing.get_type_hints()` / `inspect.signature()`. The
framework's `mount_streams` path does exactly that on `@Stream`
handlers at factory boot — and Ajolopy's no-`from __future__ import
annotations` rule means the import has to resolve at runtime, not
just at type-check time. With the symbol hidden under `TYPE_CHECKING`,
`AjolopyFactory.create(...)` raises
`NameError: name 'AsyncGenerator' is not defined` at boot, so
`ajolopy dev` returns 500 on every request.

This bug was dormant before AJ-87 (which made `@Stream` actually
mount from `@Agent` / `@Workflow` classes). Post-AJ-87, every example
boots through the mount path that calls `get_type_hints`, so the
latent forward-ref crash surfaces. Same root cause and same fix
pattern as AJ-92 (scaffold `main.py`) and AJ-95 (scaffold
workflow / mcp templates).

## Acceptance criteria

- [ ] All seven affected example agent files import
      `AsyncGenerator` at module level (not under `TYPE_CHECKING`).
- [ ] Each hoisted import carries `# noqa: TC003` plus the
      canonical "must be runtime-visible — PEP 649 + `mount_streams`"
      comment, matching `dogfood/docsbot/src/docsbot/agents/docs.py`.
- [ ] Each affected example's smoke test extends with a boot-level
      regression: build the full `AjolopyApp` via
      `AjolopyFactory.create(AppModule)` and assert `/chat` is mounted
      on `app.http.routes` (matches the AJ-87
      `tests/factory/test_stream_carrier_scan.py` pattern).
- [ ] `uv run ruff check && uv run ruff format --check` passes
      with no new violations.
- [ ] `uv run pyright` passes.
- [ ] `uv run pytest` passes (framework suite).
- [ ] `uv run pytest` passes in each affected example directory.

## Out of scope

- Touching the docsbot (already fixed in PR #149).
- Touching unrelated `TYPE_CHECKING` blocks in the same files that
  hide genuinely type-only imports.
- Re-running the dispatched verification battery — the coordinator
  handles that after this PR merges.

## Implementation notes

<!-- Filled when this item ships. Record the smoke verification
(curl output against a fresh `ajolopy dev` of an affected example)
+ any tests added beyond the existing assertions. -->
