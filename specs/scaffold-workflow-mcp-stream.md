# AJ-95 — `--feature workflow` and `--feature mcp` scaffolds expose `@Stream("/chat")`

> Tracked in [`board.json`](../board.json) as `AJ-95`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (CLI). Milestone: `v0.1`. Priority: `p0`.

## What

The `ajolopy new <name> --feature workflow` and `--feature mcp`
templates emitted a `Support` class with no HTTP surface, so the
documented next-steps flow (`uv sync && ajolopy dev`) booted a server
that returned 404 on every `curl /chat`. Only `--feature agent`
matched the killer-demo wire shape (AJ-90 added `@Stream("/chat")`
there). Two of three scaffold flavours were effectively
unexercisable.

## Fix

Both templates now mount `@Stream("/chat")` with the same
`Annotated[ChatRequest, Body()]` signature as the agent flavour.

- **workflow** flavour: handler lives on the `@Workflow` orchestrator
  (mirrors `examples/support-agent/agents/team.py` so the wire
  contract is identical regardless of how many specialists the team
  grows).
- **mcp** flavour: handler lives on the `@Agent` that owns
  `integrations=[Integrations]` (mirrors
  `examples/oncall-agent/agents/oncall.py`).

## Acceptance criteria

- [x] `ajolopy new <n> --feature workflow` scaffolds an HTTP-exposed
      `/chat` endpoint on the `@Workflow` class.
- [x] `ajolopy new <n> --feature mcp` scaffolds the same on the
      `@Agent` that owns `integrations`.
- [x] Regression tests per feature variant in
      `tests/cli/test_new_wizard.py`.
- [x] `test_smoke_import` extended to assert `/chat` is mounted on
      the Starlette router after the generated package imports.

## Shipped

PR #160 — commit `9d061d9` — released in `v0.1.8` (tag-move).
