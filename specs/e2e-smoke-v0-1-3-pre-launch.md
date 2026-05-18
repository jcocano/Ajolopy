# AJ-79 — E2E functional smoke of v0.1.3 from PyPI before HN launch

> Tracked in [`board.json`](../board.json) as `AJ-79`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `chore` (pre-launch QA). Milestone: `v0.1`. Priority: `p0`.

## What

Walk the canonical "fresh visitor to HN" journey end-to-end against
`ajolopy==0.1.3` as published to PyPI, find any friction that would
bounce a real visitor, and either land a fix or file the bug before
the launch goes live.

Single PR per discovered bug; this item itself does not ship code, it
ships a report.

## Why

The framework code path was audited in pieces (CLI scaffold fix
in #133, pyright clean-up in #134, docsbot corpus rebuild in #137).
None of those exercised the **journey a HN visitor actually takes**:

```bash
pip install ajolopy           # → does the published wheel resolve?
ajolopy new myapp             # → does the wizard produce a clean project?
cd myapp && uv sync           # → does the generated pyproject lock?
ajolopy doctor                # → does diagnostic come back clean?
ajolopy generate agent foo    # → do scaffolds produce running code?
ajolopy dev                   # → does the server start?
curl localhost:8000/...       # → do tokens stream back?
```

A single broken step kills first-impression for a new user. The
launch surface is functional > marketing — every friction point is
worth catching now.

## Sub-tests (parallelizable)

Each subtask is independent and runs in its own clean directory. The
maintainer (or a delegated agent) does each, reports pass/fail with
exact repro for any failure.

### A. PyPI install + import smoke
- `python -m venv /tmp/aj-smoke-a && /tmp/aj-smoke-a/bin/pip install ajolopy==0.1.3`
- `/tmp/aj-smoke-a/bin/python -c "import ajolopy; print(ajolopy.__version__)"`
- **Pass criterion**: install completes, import works, version reads `0.1.3`.

### B. `ajolopy new` wizard — provider matrix
- Run `ajolopy new test-anthropic --llm anthropic --yes` (or interactive).
- Repeat for `--llm openai`, `--llm gemini`, `--llm universal`.
- For each: `cd test-<provider> && uv sync`.
- **Pass criterion**: each `new` produces a project whose `uv sync`
  succeeds and whose generated `pyproject.toml` is internally
  consistent.

### C. `ajolopy generate` scaffolds in a generated project
- In one of the projects from (B): run `ajolopy generate agent
  support`, `ajolopy generate workflow team`, `ajolopy generate eval
  smoke`, `ajolopy generate tool lookup`, `ajolopy generate controller
  api`, `ajolopy generate module billing`, `ajolopy generate service
  notifier`.
- For each generated file: parses as Python (via `python -c
  "import ast; ast.parse(open(...).read())"`), and any `model="..."`
  or `coordinator="..."` literal is a key in the pricing catalog (or
  is a `{placeholder}` substituted by the wizard).
- **Pass criterion**: every `generate` exits 0 and the generated file
  passes both the AST and the model-string check.

### D. `ajolopy doctor`
- In a generated project from (B): `ajolopy doctor`.
- **Pass criterion**: exits 0 with no red flags for the obvious setup
  (Python version OK, dependencies installed, env-vars at least
  warned-about, no traceback).

### E. `ajolopy dev` + curl against a real LLM
- In a project from (B) configured for `--llm universal`, override the
  `ollama` prefix's base_url to a running LM Studio (`http://127.0.0.1:1234/v1`)
  and point the agent at a locally-served model.
- Start `ajolopy dev` in the background.
- `curl -N -X POST http://localhost:8000/chat -H 'Content-Type:
  application/json' -d '{"message": "say hi"}'`.
- **Pass criterion**: server starts without traceback, curl receives
  SSE tokens, response is non-empty plausible text.

### F. Quickstart walkthrough on the published docs site
- Fetch <https://jcocano.github.io/Ajolopy/quickstart/>.
- Execute the commands from a fresh `/tmp` directory exactly as
  written.
- **Pass criterion**: every command in the quickstart succeeds in
  order; the final stated behaviour (`curl /chat` returns tokens) is
  observed.

### G. Broken-link audit
- Run `lychee README.md docs/**/*.md` (or equivalent) over the repo's
  user-facing markdown plus the published docs site.
- **Pass criterion**: zero broken external links, zero broken internal
  references.

### H. Docsbot live deployment
- Identify the docsbot's live URL (likely a fly.io subdomain referenced
  in `dogfood/docsbot/fly.toml` or its README).
- Pose a question whose answer cites a model string ("what model does
  the `@Agent` decorator use in the quickstart").
- **Pass criterion**: the bot answers with `claude-opus-4-7` (the
  corpus shipped in #137), not `claude-sonnet-4-7`. If the bot is not
  yet redeployed, file the redeploy as a sub-task.

## Out of scope

- Editing the killer demo, README, or launch comms — those are
  separate (and largely already done in the v0.1 launch artifacts).
- Recording the demo video — explicitly the maintainer's task per
  `specs/launch-comms.md`.
- Adding new tests to `tests/` — this item produces a report, not a
  test suite. If a bug surfaces, file a separate `fix(...)` item that
  ships both the fix and its regression test.

## Acceptance criteria

- [ ] Each sub-test (A–H) has a recorded pass / fail result with exact
      repro (one paragraph each).
- [ ] Every fail has either a landed fix PR linked, or a filed `fix`
      board item linked, or a documented decision to defer (with
      rationale).
- [ ] No `p0` / `p1` fails are deferred — they ship before the launch
      goes live.

## Implementation notes

<!-- Filled when this item ships. One paragraph per sub-test:
"A: pass — exact command + observed version", "C: fail on generate
service — AttributeError, see AJ-XX", etc. -->
