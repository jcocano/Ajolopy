# AJ-73 — `examples/README.md` index

> Tracked in [`board.json`](../board.json). Type=docs, priority=p2,
> milestone=v0.1.x.

## What

Add `examples/README.md` as the index of the v0.1 example tree. Each
example already ships its own walkthrough; the index is the
**triage page** a reader lands on when they click `examples/` in
GitHub. It answers two questions:

1. Which example matches the production problem I'm solving today?
2. Which Ajolopy primitives does it exercise?

The published docs site has [`docs/next-steps.md`](../docs/next-steps.md)
for the same purpose, but `examples/README.md` is what GitHub renders
inline when browsing the folder — it should stand on its own.

## Scope

A single new file: `examples/README.md`. No changes to the per-example
READMEs, no changes to source code, no changes to tests. The page
groups the six examples by production scenario and links each one to
its own walkthrough.

Voice + structure mirror the project's existing READMEs — sober,
technical, no marketing fluff. Each entry has:

- A one-sentence description.
- A "Reach for this when..." bullet listing the production scenarios
  the example maps onto.
- The Ajolopy primitives the example exercises.
- A link to the example's own README.

The page closes with pointers to `dogfood/docsbot/` (the in-repo
dogfood app) and the docs-site tutorial / reference pages.

## Out of scope

- New examples. The set stays at the six that ship today.
- Per-example README polish. Each example's README is already
  authored under its own board item.
- A docs-site page mirroring this index. `docs/next-steps.md` already
  lists the examples for site readers; duplicating the content into
  `docs/examples.md` is post-v0.1.

## Acceptance criteria

- [x] `examples/README.md` lists every example in `examples/` with a
      one-sentence description + "reach for this when" bullets +
      primitives exercised + link to its own README.
- [x] Ordering reflects production-relevance (multi-turn / RAG /
      external HTTP / MCP / local LLM), not creation order.
- [x] Page footer points readers at `dogfood/docsbot/`, the docs site,
      and the contributing entry point.
- [x] `uv run --group docs mkdocs build --strict` stays green (the
      index lives outside `docs/` so the site build is unaffected, but
      verify no link rot in the per-example READMEs that this index
      points to).
- [x] AJ-73 transitions to `done` as the final commit on this PR (new
      project convention from AGENTS.md).
