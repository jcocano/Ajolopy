# AJ-96 — Refresh `openai` + `gemini` default model strings in scaffold

> Tracked in [`board.json`](../board.json) as `AJ-96`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (CLI). Milestone: `v0.1`. Priority: `p0`.

## What

`ajolopy new --llm openai` scaffolded `gpt-4o` (`gpt-4o-mini`
fallback); `--llm gemini` scaffolded `gemini-2.0-flash-exp`
(`gemini-2.0-flash` fallback). Both pairs have been superseded by
their upstream providers: `gpt-4o` is now listed as a legacy model
with deprecation noise on first request, and `-exp` is Google's
research-only suffix that should never ship in a production
scaffold. A new visitor picking either provider hit a
model-not-found / deprecation warning on their very first request —
the same launch-readiness damage AJ-80 / AJ-90 already addressed for
Anthropic.

## Fix

Bump the per-provider defaults to current GA flagships paired with a
same-family slimmer sibling, mirroring the `claude-opus-4-7` +
`claude-haiku-4-5` shape of the killer demo:

- `--llm openai`: `gpt-5` (`gpt-5-mini` fallback).
- `--llm gemini`: `gemini-2.5-flash` (`gemini-2.5-flash-lite`
  fallback).

Every model string is verified against the authoritative
`src/ajolopy/observability/pricing.json` catalog (AJ-80 contract
template tests already enforce this), and the pinned-value provider
variants test is updated alongside.

## Acceptance criteria

- [x] Wizard `--llm openai` emits `gpt-5` + `gpt-5-mini`.
- [x] Wizard `--llm gemini` emits `gemini-2.5-flash` +
      `gemini-2.5-flash-lite`.
- [x] Every model string present in `pricing.json`.
- [x] Pinned-value test updated.

## Shipped

PR #159 — commit `98b589b` — released in `v0.1.8` (tag-move).
