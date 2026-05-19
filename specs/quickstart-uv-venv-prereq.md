# AJ-82 — Quickstart: add `uv venv` prerequisite

> Tracked in [`board.json`](../board.json) as `AJ-82`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (docs). Milestone: `v0.1`. Priority: `p1`.

## What

The published quickstart told new users to run `uv pip install ajolopy`
as the very first command. On a clean machine that fails with
`No virtual environment found; run uv venv ...` because nothing in
the page asks the user to create a venv first. The canonical
fresh-install path was broken.

## Fix

Insert a short prerequisite step right before the install command
that creates and activates a Python 3.14 venv (`uv venv --python 3.14
.venv` + `source .venv/bin/activate`), plus an admonition explaining
why the interpreter is pinned — Ajolopy requires 3.14+ (PEP 649), and
the explicit `--python 3.14` avoids picking up an older default on
the user's machine. `install.md` already cross-links from quickstart,
so the venv step stays inline for the 5-minute path.

## Acceptance criteria

- [x] Quickstart page includes a `uv venv --python 3.14 .venv` +
      `source .venv/bin/activate` step before `uv pip install`.
- [x] Admonition explains the 3.14 pin.
- [x] AJ-85 (same gap in `install.md`) follows the same shape.

## Shipped

PR #140 — commit `c2f8c8e` — released in `v0.1.4`.
