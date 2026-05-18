# AJ-85 — Install docs missing `uv venv` prerequisite

> Tracked in [`board.json`](../board.json) as `AJ-85`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Type: `fix` (docs bug). Milestone: `v0.1`. Priority: `p1`.

## What

`docs/install.md` shows users `uv pip install ajolopy` (and its
verifying-the-install variant) without first instructing them to
create a virtual environment via `uv venv`. The exact same gap was
fixed for the quickstart by AJ-82; install.md was missed because the
original smoke focused on the quickstart entry point.

A user who lands on the install page from the README badges (rather
than via the quickstart) hits `error: No virtual environment found`
on the first command they're told to run. Same first-impression
failure pattern as AJ-82.

## Why

AJ-82 already fixed this for `docs/quickstart.md` (PR #140). The
install page is the *other* main entry point — linked directly from
the README install instructions, the PyPI project page, and any
"installation" anchor in launch comms. Leaving it broken means roughly
half the inbound traffic on launch day still hits the venv error.

When AJ-82's worker fixed the quickstart, it noticed the same gap in
install.md but per scope discipline did not bundle the fix. Filing
AJ-85 closes the loop.

## Acceptance criteria

- [ ] `docs/install.md`'s "Core install" and "Verifying the install"
      snippets explicitly show `uv venv --python 3.14 .venv` (and
      activation) before `uv pip install ajolopy`.
- [ ] Wording style matches AJ-82's quickstart fix so the two pages
      stay consistent.
- [ ] `uv run --group docs mkdocs build --strict` passes.
- [ ] No other `docs/**.md` page tells the user to `uv pip install`
      without venv setup. (Quick grep: `grep -rn "uv pip install" docs/`
      and decide per match.)

## Implementation pointers

- Single file edit: `docs/install.md`. Likely 5–10 lines added.
- Reference the AJ-82 PR (#140) for the exact prose pattern the
  quickstart fix introduced.
- If `install.md` already cross-links to a "prerequisites" section
  elsewhere, prefer linking over duplicating.

## Out of scope

- Touching `docs/quickstart.md` (already shipped via AJ-82).
- Auditing every other `.md` file for unrelated install advice. This
  item is scoped to the install + verifying-install snippets that
  failed during the AJ-79 smoke walk.

## Implementation notes

<!-- Filled when this item ships. Record the exact prose used so it
matches AJ-82's quickstart fix, plus the result of the cross-file
grep for any other `uv pip install` instances. -->
