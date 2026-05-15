# AJ-49 — Reference docs for each of the primitives

> Tracked in [`board.json`](../board.json) as `AJ-49`. Adds per-primitive
> reference pages to the docs site (which AJ-47 bootstraps with
> mkdocs-material).

## What

One Markdown reference page per primitive (current count after the
contract reopens: 11 AI/framework primitives + `@UseGuards`). Each
page documents the public signature, common usage, escape hatches,
and links to the corresponding spec file in `specs/`.

## Why

Brief dolor #7 again: a senior dev should be able to read one
reference page and KNOW how to use the primitive in 5 minutes.

## Public surface (v0.1)

### Files added

```
docs/reference/
  index.md              # Overview of every primitive
  agent.md              # @Agent
  tool.md               # @Tool
  stream.md             # @Stream
  workflow.md           # @Workflow
  mcp.md                # @MCP (consume)
  mcp-server.md         # @MCPServer (publish)
  eval.md               # @Eval (covers @Metric too)
  module.md             # @Module
  injectable.md         # @Injectable
  controller.md         # @Controller
  use-guards.md         # @UseGuards
```

### Page structure (every page)

```markdown
# `@<Primitive>`

> Spec: [`specs/<slug>.md`](../../specs/<slug>.md) · Item: `AJ-N`

## Purpose

One paragraph: what the primitive does, when to reach for it.

## Signature

```python
def Primitive(...) -> ...: ...
```

## Quick example

```python
# 8-15 line code block demonstrating the magical default.
```

## Kwargs

| Kwarg | Type | Default | Description |
|-------|------|---------|-------------|

## Escape hatches

Bullet list of subclass / override / kwarg-instance forms.

## Common gotchas

3-5 bullets.

## See also

- Spec, tutorial section, related primitive.
```

### Reference index page (`docs/reference/index.md`)

A table grouping the primitives:

```markdown
# Reference

## Agent primitives (8)

| Decorator | Purpose | When to use |
|---|---|---|

## Framework primitives (3 + 1 middleware)

| Decorator | Purpose | When to use |
|---|---|---|
```

### `mkdocs.yml` update

This item EXTENDS the `mkdocs.yml` that AJ-47 ships. Add a
`Reference:` section under `nav:` with all 12 pages. Merge order:
AJ-47 first, then rebase AJ-49 to add the nav section.

```yaml
nav:
  - Home: index.md
  - Quickstart: quickstart.md
  - Install: install.md
  - Reference:
      - Overview: reference/index.md
      - "@Agent": reference/agent.md
      - "@Tool": reference/tool.md
      - "@Stream": reference/stream.md
      - "@Workflow": reference/workflow.md
      - "@MCP": reference/mcp.md
      - "@MCPServer": reference/mcp-server.md
      - "@Eval": reference/eval.md
      - "@Module": reference/module.md
      - "@Injectable": reference/injectable.md
      - "@Controller": reference/controller.md
      - "@UseGuards": reference/use-guards.md
  - Next steps: next-steps.md
```

## Cross-cuts

### AJ-47 — depends on (mkdocs.yml + docs/ scaffold)
- Merge order matters; this PR rebases on top of AJ-47.

### No code changes
- This is a docs-only PR.

## Out of scope

- Tutorial (AJ-48).
- API auto-generation from docstrings (mkdocs-autorefs / griffe) →
  v0.2.
- Examples / cookbook recipes — those are AJ-51 / AJ-52 / AJ-50.

## Acceptance criteria

- [ ] 11 primitive pages + 1 overview page exist.
- [ ] Each page follows the documented section structure.
- [ ] Each page links to its `specs/<slug>.md`.
- [ ] `mkdocs.yml` `nav:` includes the new Reference section.
- [ ] `uv run mkdocs build --strict` succeeds (no broken links).
- [ ] Every primitive's "Quick example" code block uses real, working
      imports from `ajolopy` (no pseudo-code).

## Implementation pointers

- Source each page's content from the corresponding `specs/<slug>.md`
  Implementation notes + Public surface sections. Don't duplicate —
  link to the spec for full detail.
- Pages should be 80-150 lines each. Tighter than the spec.
- All pages in `docs/reference/`.

## Implementation notes

(Empty — populated by the implementation PR.)
