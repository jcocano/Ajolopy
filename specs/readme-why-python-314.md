# AJ-76 — README: explain Python 3.14+ requirement

> Tracked in [`board.json`](../board.json). Type=docs, priority=p2,
> milestone=v0.1.x.

## What

Add a short **"Why Python 3.14+"** section to the root `README.md`,
placed immediately after the `## Install` block (which already states
the requirement but not the reason).

The new section is four bullets — terse, factual, framework-focused —
explaining the design decisions that make 3.14 the minimum supported
version. No new prose anywhere else in the README; existing sections
stay untouched.

## Why

External v0.1.0 reviewers flagged "Python 3.14 as the minimum" as a
deployment risk (recorded in `specs/v0-1-1-readme-classifier-models.md`
under *Out of scope*, where the project chose not to walk it back). The
requirement is intentional and load-bearing for the framework's
type-driven DI and runtime introspection — so the README should *own*
the choice instead of leaving it as a bare version constraint readers
have to rationalise on their own.

The four reasons are not new policy; they are already enforced in
`CLAUDE.md` ("Python 3.14+. `from __future__ import annotations` is
prohibited — PEP 649 makes it unnecessary in 3.14 and hides typing
errors at runtime"). This task surfaces that reasoning to the README.

## Scope

### Single edit in `README.md`

Insert the section between the current `## Install` block (ends at the
line listing optional extras) and the `## The killer demo` heading.

```markdown
## Why Python 3.14+

- **PEP 649** — deferred evaluation of annotations is native, so
  `from __future__ import annotations` is forbidden in this codebase
  (it would hide real typing errors at runtime).
- **Pyright strict pays off** — runtime introspection of type hints
  (`inspect.get_annotations`) works without the lazy-eval workarounds
  older Pythons need.
- **DI by type-hints** — Ajolopy resolves `@Injectable` providers via
  real annotation objects; PEP 649 makes that cheap and correct.
- **Modern stdlib** — `asyncio.TaskGroup`, structural pattern matching,
  and the new error-message machinery are assumed everywhere.
```

## Out of scope

- Any prose change outside the new section.
- Docs site (`docs/install.md` etc.) — separate task if/when the same
  rationale needs to live in the long-form docs. v0.1.x scope here is
  the README only.
- A "minimum-Python policy" doc — the README bullets are sufficient
  for v0.1.x.
- Lowering the floor to 3.12/3.13 — the requirement stays.

## Acceptance criteria

- [ ] AJ-76 promoted to ready, claimed, branch
      `docs/readme-why-python-314`.
- [ ] `README.md` contains a `## Why Python 3.14+` section placed
      directly after the `## Install` block.
- [ ] Section body matches the four-bullet skeleton in Scope (wording
      may be polished, structure must hold).
- [ ] No other section in `README.md` is modified.
- [ ] `uv run ruff check` clean (no Python changed, but verify).
- [ ] `uv run ruff format --check` clean.
- [ ] AJ-76 transitions to `in_review` when the PR opens and `done`
      after merge (current AGENTS.md convention).
