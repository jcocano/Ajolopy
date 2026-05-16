# AJ-72 — Cross-provider fallback in local-ollama example

> Tracked in [`board.json`](../board.json) as `AJ-72`. Type=docs,
> priority=p2, milestone=v0.1.x.

## What

Add `fallback="claude-haiku-4-5"` to the `CodeReviewer` agent in
`examples/local-ollama/`. The example currently has no fallback —
documented as a deliberate omission ("a single-laptop Ollama daemon
has nothing to fall back to"). That framing made sense before AJ-69
(lazy fallback instantiation) shipped, but it now leaves the
production-realistic **cross-provider fallback** pattern unshown by
any example in the repo.

After this change the example demonstrates:

- Primary: `ollama:llama3.3` (local, no API key).
- Fallback: `claude-haiku-4-5` (cloud, lazy).
- Because AJ-69 made fallback instantiation lazy, the example boots
  cleanly with `ANTHROPIC_API_KEY` unset. The Anthropic provider only
  gets constructed (and the env var only gets validated) the first
  time the local Ollama call fails — typically a retriable timeout or
  a connection refused when the daemon is down.

## Why

Cross-provider fallback is one of the framework's nicest
production-readiness wins. The Brief v4.0 lists it as production pain
#5: "Anthropic outage = app caída". Before AJ-69, demonstrating it in
a local-primary example was awkward because the eager Anthropic
provider construction would force every reader to set
`ANTHROPIC_API_KEY=test-dummy` just to import the example. AJ-69
removed that friction. This item ports the demonstration into the
runnable example so the wedge user can see the pattern end-to-end.

## Out of scope

- Cross-provider fallback for the OTHER examples (`support-agent`,
  `web-research`, `oncall-agent`, `memory-assistant`,
  `contextual-rag`). They all use a same-vendor fallback today
  (`claude-opus-4-7` → `claude-haiku-4-5`), which is its own
  legitimate pattern and worth keeping.
- Adding a third-tier fallback (`fallback=["claude-haiku-4-5",
  "gpt-4o-mini"]`). The example is meant to be readable; one fallback
  is the canonical demo.
- Testing the fallback fire path against a live LLM. The smoke test
  stays network-free; the fallback is **statically observable** via
  the agent's runtime metadata (`_models` carries the fallback model
  + its provider key).

## Acceptance criteria

- [x] `examples/local-ollama/src/local_ollama/agents/reviewer.py` —
      `@Agent(...)` gains a `fallback="claude-haiku-4-5"` kwarg.
- [x] `examples/local-ollama/README.md` — the "Why no `fallback=`?"
      sentence is replaced with the cross-provider-fallback
      explanation. Calls out the AJ-69 lazy behaviour: no
      `ANTHROPIC_API_KEY` required until the local primary fails.
- [x] `examples/local-ollama/.env.example` — gains an optional
      `ANTHROPIC_API_KEY=` placeholder with a comment explaining when
      it's actually needed.
- [x] `examples/local-ollama/tests/conftest.py` — unchanged. The
      smoke test stays network-free and the fallback is lazy, so
      there is nothing to set up.
- [x] `examples/local-ollama/tests/test_smoke.py` — extend the
      existing decorator-metadata assertions to confirm:
      `CodeReviewer._agent_runtime._models[0][0] == "ollama:llama3.3"`
      and `CodeReviewer._agent_runtime._models[1][0] == "claude-haiku-4-5"`.
      The fallback entry's provider instance MUST be `None` at this
      point (AJ-69 lazy build), which is the assertion that ties the
      example to the framework feature.
- [x] AJ-72 transitions to `done` as the last commit on this PR (per
      the new project convention).
