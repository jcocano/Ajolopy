# AJ-71 — Migrate local-ollama example to use AJ-68 + AJ-70

> Tracked in [`board.json`](../board.json) as `AJ-71`. Type=docs,
> priority=p2, milestone=v0.1.x.

## What

The `examples/local-ollama/` README (AJ-66) was authored before `AJ-68`
(env-var support for `${PREFIX}_BASE_URL`) and `AJ-70` (pricing-catalog
silence for local prefixes) shipped. It explicitly documented the
**workaround** — register a custom `UniversalOpenAIProvider` instance
with `base_urls={"ollama": "..."}` — and noted that the framework
**did not** read `OLLAMA_BASE_URL`. Both of those statements are now
wrong.

This item refreshes the README + `.env.example` to reflect the new
behaviour:

- `OLLAMA_BASE_URL` is read by the universal provider at first-request
  time (AJ-68). No code change needed to point at a remote Ollama, LM
  Studio, vLLM, or any other OpenAI-compatible local server.
- `ollama:*` is silenced by default in the pricing catalog (AJ-70). No
  "Unknown model" warning fires for local models. Custom prefixes can
  be silenced via `AjolopyFactory.create(pricing_silence={"vllm"})`.

## Why

The launch examples are the project's most-read code. Documenting a
workaround that the framework now obsoletes confuses readers and
undermines the AJ-68 + AJ-70 improvements. The migration is small —
two files (`README.md` + `.env.example`), no source code, no tests —
but high-leverage because every reader of the local-ollama example
sees these docs.

## Audit findings

Surveyed every example + `dogfood/docsbot/` for migration touchpoints.

- **local-ollama**: real changes (this item).
- **support-agent / web-research / oncall-agent / memory-assistant /
  contextual-rag**: each uses `model="claude-opus-4-7"` as the
  *primary*. The `ANTHROPIC_API_KEY=test-dummy` setter in their
  `tests/conftest.py` validates the **primary** at decoration time and
  must stay — AJ-69 made the *fallback* lazy, not the primary. No
  changes.
- **dogfood/docsbot**: same — primary is Anthropic. No changes.

## Out of scope

- Removing the `ANTHROPIC_API_KEY=test-dummy` test setters in other
  examples. They still validate the primary; AJ-69 only made the
  fallback lazy.
- Adding `pricing_silence=` calls to any example. No example uses a
  custom non-ollama local prefix today.
- Surfacing `base_urls={...}` through `@Agent` directly. Tracked
  separately as a post-v0.1 follow-up.

## Acceptance criteria

- [x] `examples/local-ollama/README.md` — "Remote Ollama" section
      rewritten to use the `OLLAMA_BASE_URL` env var instead of the
      old register-a-custom-provider workaround. LM Studio and vLLM
      flagged as common alternatives.
- [x] `examples/local-ollama/README.md` — line "framework reads no
      environment variable for the `ollama:` prefix" removed; replaced
      with the new env-var-first description that cites AJ-68.
- [x] `examples/local-ollama/README.md` — explicit mention of AJ-70's
      default-silence for `ollama:*` and the `pricing_silence=`
      escape hatch for custom prefixes.
- [x] `examples/local-ollama/.env.example` — comment block above
      `OLLAMA_BASE_URL` rewritten to reflect that the framework reads
      it.
- [x] No source code touched. No tests touched. `mkdocs build --strict`
      remains green (this example does not ship docs pages under
      `docs/`).
- [x] AJ-71 transitions to `done` as the last commit on this PR (new
      project convention from AGENTS.md).
