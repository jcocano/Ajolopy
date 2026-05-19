# AJ-81 — `ajolopy new --llm universal` in the wizard

> Tracked in [`board.json`](../board.json) as `AJ-81`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (CLI). Milestone: `v0.1`. Priority: `p0`.

## What

`ajolopy new <name> --llm universal` errored with
`invalid choice: 'universal'`. Brief v4.0 lists the universal
OpenAI-compatible provider as non-negotiable for v0.1, and the launch
comms already advertise it.

## Fix

Promote `universal` to a first-class wizard value. Universal routes by
a `"<prefix>:<model>"` string, so the wizard gains two follow-up flags
— `--universal-prefix` (ollama / groq / together / mistral / deepseek
/ openrouter) and `--universal-model` — and emits the right model
literal plus per-prefix env-var docs into the generated
`.env.example`. Default scaffold is `ollama:llama3.3` to give a
zero-cost local path with no API key (mirrors `examples/local-ollama`).

## Acceptance criteria

- [x] `ajolopy new <name> --llm universal` accepts the value.
- [x] `--universal-prefix` covers all 6 upstreams; defaults to ollama.
- [x] `--universal-model` overrides the per-prefix default.
- [x] Scaffold renders correct `.env.example` per prefix.
- [x] Next-steps message surfaces the right env var per prefix.
- [x] Tests in `tests/cli/test_new_wizard.py` cover all variants.

## Shipped

PR #144 — commit `4bfd2b5` — released in `v0.1.4`.
