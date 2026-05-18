# AJ-90 — Scaffold templates match the README killer demo

> Tracked in [`board.json`](../board.json) as `AJ-90`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (CLI templates). Milestone: `v0.1`. Priority: `p0`.

## What

The scaffolded `support.py` produced by `ajolopy new --feature agent`
(and the equivalent from `ajolopy generate agent`) now matches the
README's killer demo shape: `@Agent` with `fallback=`, `@Tool` with a
realistic body (`lookup_order` returning a status dict), and `@Stream`
with `Annotated[ChatRequest, Body()]`.

## Why

The README's 12-line killer demo is the framework's headline pitch.
Before this fix, `ajolopy new` shipped a simpler placeholder agent
(`echo` tool, plain `message: str` on the stream method). Visitors who
copied the README hoping the wizard would generate the same code
landed on a different file and lost trust in the documentation.

The principle: the scaffold MUST be what the README promises.

## Approach

Rewrite both templates (`src/ajolopy/cli/commands/_templates/new/feature_agent/.../support.py.tmpl`
and `src/ajolopy/cli/commands/_templates/generate/agent/agent.py.tmpl`)
to mirror the README block. For the `new --feature agent` template,
the model strings stay parametric via `{llm_model}` + `{llm_fallback}`
substitutions (so `--llm openai/gemini/universal` get coherent
provider-matched defaults, not hard-coded Anthropic). For the
`generate agent` template, the model strings are hard-coded to the
README's `claude-opus-4-7` / `claude-haiku-4-5` because there is no
provider context at generate time.

## Acceptance criteria

- [x] `ajolopy new acme --llm anthropic --feature agent --yes` produces
      a `support.py` whose body matches the README's killer demo block
      byte-for-byte (modulo the class name substitution).
- [x] `ajolopy generate agent foo` produces the same shape with `class Foo`.
- [x] The other `--llm <provider>` renders use coherent per-provider
      defaults (gpt-4o-mini, gemini-2.0-flash, etc.) rather than
      hard-coded Anthropic model strings.
- [x] Existing `tests/cli/generate/` and `tests/cli/new/` suites
      continue to pass, including the AJ-80 model-string regression
      check (all literal model names in templates must be in
      `pricing.json`).

## Implementation notes

Shipped in PR #153, commit `20ccad6`. Per-provider fallback table
added to `_ProviderDefaults` in `new.py`. Smoke comparison verified
against the README's killer demo block.
