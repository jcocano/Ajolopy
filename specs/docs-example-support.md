# AJ-50 — Full support-agent example (the 3-step arc end-to-end)

> Status: backlog → ready · Type: docs · Priority: p1 · Milestone: v0.1
> Blocks: AJ-57 (public v0.1 launch).
> Blocked by: AJ-48 (the prose tutorial — `done`).

## Goal

Ship the **runnable companion** to [`AJ-48`'s tutorial](../docs/tutorial/index.md).
After this lands, a reader can:

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/support-agent
uv sync
cp .env.example .env  # set ANTHROPIC_API_KEY
ajolopy dev
```

…and watch every code block from Steps 1, 2 and 3 of the tutorial run end-to-end.

This is the second-highest-leverage docs deliverable of v0.1 (after AJ-48 itself):

- It is the "fork-it" surface for anyone evaluating Ajolopy.
- It unblocks [`AJ-57`](../board.json) (public launch — the launch README links the example).
- It is what the [`docs/next-steps.md`](../docs/next-steps.md) page and the
  [tutorial overview](../docs/tutorial/index.md) currently point at as a
  `Tracked at board.json` placeholder.

## Structure

The example lives under `examples/support-agent/` at the repository root:

```
examples/support-agent/
  README.md                       # voice matches docs/quickstart.md
  .env.example                    # ANTHROPIC_API_KEY + optional GITHUB_TOKEN
  pyproject.toml                  # depends on the local ajolopy via [tool.uv.sources]
  src/support_agent/
    __init__.py
    main.py                       # async def app() — ajolopy dev entry point
    app_module.py                 # @Module wiring (Step 1 vs Step 3 toggled by env)
    agents/
      __init__.py
      support.py                  # Step 1 — single @Agent + @Tool + @Stream
      team.py                     # Step 3 — Triage / Billing / Technical + @MCP + @Workflow
  evals/
    support.jsonl                 # ≥3 sample rows for SupportEval
    support_eval.py               # Step 2 — @Eval(agent=Support) + 2 @Metrics
    support_team.jsonl            # ≥3 sample rows for TeamEval
    team_eval.py                  # Step 3 — @Eval(workflow=SupportTeam) + 2 @Metrics
  tests/
    test_smoke.py                 # decorator metadata only — no provider calls
```

`@Module` wires either `Support` (Step 1) or `SupportTeam` (Step 3) depending on
the `SUPPORT_AGENT_MODE` env var; the default is `team` so the
out-of-the-box `ajolopy dev` exercises the full Step 3 surface.

## Acceptance criteria

- [ ] `examples/support-agent/` exists with the structure documented above.
- [ ] `examples/support-agent/src/support_agent/agents/support.py` mirrors the
      Step 1 tutorial code (a `Support` `@Agent` with `lookup_order` `@Tool`,
      `ChatRequest` Pydantic model, `@Stream("/chat")` over SSE,
      `fallback="claude-haiku-4-5"`).
- [ ] `examples/support-agent/src/support_agent/agents/team.py` mirrors the
      Step 3 tutorial code (`Triage`, `Billing`, `Technical` `@Agent`s with
      `issue_refund` tool; `Integrations` `@MCP` block with the GitHub MCP
      server; `SupportTeam` `@Workflow` with `coordinator`, `agents`,
      `integrations`, and a `@Stream("/chat")` handler).
- [ ] `examples/support-agent/evals/support_eval.py` mirrors the Step 2 code
      (LLM-judge `helpful` metric + deterministic `safe` metric).
- [ ] `examples/support-agent/evals/team_eval.py` mirrors the Step 3
      workflow-level `@Eval(workflow=SupportTeam)` with `addresses_intent`
      and `mentions_domain` metrics.
- [ ] `examples/support-agent/evals/support.jsonl` and
      `examples/support-agent/evals/support_team.jsonl` each ship with at
      least three sample cases that match the dataset shape the metrics expect.
- [ ] `examples/support-agent/pyproject.toml` uses `[tool.uv.sources]` to
      point `ajolopy` at the parent repo (`{ path = "../..", editable = true }`)
      so the example never depends on a published PyPI release.
- [ ] `examples/support-agent/README.md` walks step-by-step: install, env,
      `ajolopy dev`, three curl examples (Step 1 single-agent invocation;
      Step 2 — running `ajolopy eval`; Step 3 — `/chat` against the workflow).
      Voice matches `docs/quickstart.md` and the AJ-48 tutorial pages.
- [ ] `examples/support-agent/tests/test_smoke.py` asserts the agents
      instantiate and tools register at import time. It does NOT call any
      provider. No `monkeypatch` on the SDK.
- [ ] Repository root `README.md` gains a `## Examples` section pointing at
      `examples/support-agent/`.
- [ ] `docs/tutorial/index.md` and `docs/next-steps.md` link the example at
      `https://github.com/jcocano/Ajolopy/tree/main/examples/support-agent`
      (absolute URL — the docs site builds with `strict: true`, relative
      cross-tree links would fail to resolve).
- [ ] `uv run --group docs mkdocs build --strict` passes locally.
- [ ] `uv run ruff check examples/support-agent` passes with zero violations.
- [ ] `uv run ruff format --check examples/support-agent` passes.
- [ ] `uv run pyright examples/support-agent` passes (strict typing).
- [ ] From inside the example directory:
      `cd examples/support-agent && uv sync && uv run pytest tests/`
      passes (smoke test only).

## Out of scope

- A second example app (deploy / dogfood). Those are AJ-51 / AJ-52 / AJ-54.
- A demo video or animated gif. That is AJ-57.
- New primitives, kwargs, or eval helpers. If a snippet wants something the
  framework does not yet expose, the snippet adapts — not the framework.
- Translations. v0.1 example app is English-only.
- Real production tool implementations. `lookup_order` and `issue_refund`
  stay as the docstring-only stubs the tutorial uses — the example exists
  to demonstrate the framework's shape, not to ship a real support system.

## Implementation notes

- **API drift between Brief and current source.** The example mirrors the
  AJ-48 prose tutorial, but `@Agent` no longer accepts `trace=True` (OTel is
  always on; spans are no-ops without the `otel` extra). The example drops
  the `trace=True` kwarg and the README notes the same. Similarly, `@Workflow`
  has no `trace=` kwarg.
- **`@MCP` is declared but the GitHub MCP server is optional at runtime.**
  Without `ajolopy[mcp]` + `GITHUB_TOKEN`, the MCP layer marks the server
  unhealthy and the workflow still serves — the README documents this.
- **`@Module` wiring.** A single `AppModule` wires either `Support` (Step 1)
  or `SupportTeam` (Step 3) based on the `SUPPORT_AGENT_MODE` env var; the
  default is `team` (Step 3) so the out-of-the-box `ajolopy dev` exercises
  the full surface. A clear README section calls out how to flip the toggle.
- **Path-based ajolopy dep.** `[tool.uv.sources] ajolopy = { path = "../..",
  editable = true }` keeps the example self-contained inside the repo so
  `uv sync` works the moment the user clones — no published PyPI release
  required. CI does not run `uv sync` on the example (the smoke test is
  exercised by the example's own pytest invocation in the acceptance list,
  not by the repo-level CI), but `uv run pyright examples/support-agent`
  does.
- **`mkdocs build --strict` is the docs gate.** Strict mode would catch
  any broken cross-tree link in the docs that now refers to the example —
  hence the absolute GitHub URL pattern in the acceptance criteria.
- **Tests are decorator-metadata-only.** No `pytest.mark.anyio` plumbing,
  no monkeypatching the Anthropic SDK. The single test exercises
  `hasattr(Support, "run")`, `hasattr(Support, "stream")`, and the
  `@Tool` markers — enough to catch import-time regressions, not enough
  to depend on network or env.
