# AJ-100 — Restructure new/generate scaffolds to feature-per-@Module layout

> Tracked in [`board.json`](../board.json) as `AJ-100`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `refactor` (CLI templates). Milestone: `v0.1`. Priority: `p0`.

## What

Both scaffolders — `ajolopy new` and `ajolopy generate` — emit code
organised by **feature module** instead of by primitive type.

A fresh `ajolopy new acme --feature agent --yes` produces:

```
src/acme/
├── support/
│   ├── __init__.py
│   ├── support_agent.py        # @Agent
│   └── support_module.py       # @Module(agents=[Support])
├── app_module.py               # @Module(imports=[SupportModule, ...])
├── config.py
└── main.py
tests/
└── support/
    └── test_support_agent.py
```

`ajolopy generate agent leads --module sales` writes
`src/<package>/sales/leads_agent.py` and registers it in
`src/<package>/sales/sales_module.py` (creating that module if
missing). Without `--module`, generate creates a fresh `leads/`
feature folder with `leads_agent.py` + `leads_module.py`.

## Why

Ajolopy's positioning — "NestJS-style framework for AI-native apps" —
sells modularity as a first-class differentiator. The current scaffold
contradicts that positioning: it organises by primitive type
(`agents/`, future `tools/`, `workflows/`) and ships a single root
`AppModule`. A newcomer who opens the generated project sees the same
shape any FastAPI app could have, with no visible `@Module` boundary
beyond the root. The framework's marketing promise and its first
generated artifact are out of sync.

The feature-folder layout also enables clean extraction of a feature
into its own deployable: a `<feature>/` folder containing its module,
agent, tools, and controllers is a self-contained unit that can be
lifted into a separate Ajolopy app (or k8s Service) by copying the
folder. The primitive-bucket layout fragments a single feature across
parallel folders, blocking trivial extraction.

v0.1 has already shipped to PyPI, so this is a post-launch convention
update. Existing user projects are unaffected — users own their code
after generation. Blog posts and tutorials referencing the v0.1.x
scaffold output will need an update; doing this before v0.1 picks up
usage mass costs less than carrying two competing layouts forward.

## Approach

1. **Rewrite the `new` template tree.** Move the per-feature
   primitive file (currently
   `feature_<kind>/src/__package__/agents/support.py.tmpl`) into a
   `__feature__/` directory alongside a new
   `<feature>_module.py.tmpl` sibling. Extend the path-token map in
   `src/ajolopy/cli/commands/new.py`
   (`_PATH_TOKEN_TO_CONTEXT_KEY`) to translate the `__feature__`
   path segment to the resolved feature slug, mirroring the
   existing `__package__` mechanism. Rewrite
   `base/src/__package__/app_module.py.tmpl` to import the feature
   module and compose via `imports=[...]` rather than hoisting the
   primitive directly with `agents=[...]`.
2. **Mirror tests under the feature folder.** Move
   `base/tests/test_support.py.tmpl` to
   `base/tests/__feature__/test___feature___agent.py.tmpl`.
3. **Extend `ajolopy generate` with `--module <feature>`.** With the
   flag set, write the new file to
   `src/<package>/<feature>/<name>_<kind>.py` and append the new
   primitive's registration to `<feature>_module.py` (creating it
   if missing). Without the flag, create a new feature folder named
   after the new primitive containing both the primitive file and a
   `<name>_module.py`.
4. **File naming inside a feature folder uses the feature prefix**
   (`support_agent.py`, `support_module.py`, future
   `support_tool.py`). Rationale: editor tabs display the bare
   filename without folder context, so a prefix-less `agent.py` is
   ambiguous when multiple feature folders are open at once.
   Mirrors NestJS (`users.service.ts`, `users.controller.ts`).
5. **Documentation cascade.** Update the README "killer demo"
   block, the quickstart, the tutorial arc, the `@Module` reference
   docs, and the `support-agent` example to the new layout.

## Acceptance criteria

- [ ] `ajolopy new acme --feature agent --yes` produces a tree where
      the agent lives at `src/acme/support/support_agent.py` and
      `src/acme/support/support_module.py` exists declaring
      `@Module(agents=[Support])`.
- [ ] The generated `src/acme/app_module.py` imports `SupportModule`
      and composes via
      `@Module(imports=[SupportModule, ...], providers=[AppConfig])`.
- [ ] The generated tests live under
      `tests/support/test_support_agent.py`.
- [ ] The same shape holds for `--feature workflow` and
      `--feature mcp`.
- [ ] `ajolopy generate agent leads --module sales` writes
      `src/<package>/sales/leads_agent.py` and registers `Leads` in
      `src/<package>/sales/sales_module.py` (creating it if absent).
- [ ] `ajolopy generate agent leads` without `--module` creates a
      fresh `src/<package>/leads/` feature folder with both
      `leads_agent.py` and `leads_module.py`.
- [ ] `ajolopy generate <kind> ...` honours `--module` for every
      kind the subcommand supports (`agent`, `tool`, `workflow`,
      `controller`, `service`, `eval`).
- [ ] `tests/cli/new/` and `tests/cli/generate/` updated; full suite
      passes (`uv run pytest`).
- [ ] `pyright --strict`, `ruff check`, and `ruff format --check`
      remain green.
- [ ] README killer demo, quickstart, tutorial, and `@Module`
      reference docs updated to the new layout.

## Implementation notes

To be populated during the work.
