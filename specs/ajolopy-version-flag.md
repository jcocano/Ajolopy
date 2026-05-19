# AJ-83 — `ajolopy --version` top-level flag

> Tracked in [`board.json`](../board.json) as `AJ-83`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (CLI). Milestone: `v0.1`. Priority: `p0`.

## What

`ajolopy --version` errored with
`the following arguments are required: subcommand` and exited 2,
because the root argparse parser required a subcommand before any
flag could be handled. This is the first command most users run
after installing the CLI, so the failure was both visible and
confusing.

## Fix

Register a top-level `--version` argparse action that prints
`ajolopy <package __version__>` and exits 0 without parsing a
subcommand.

## Acceptance criteria

- [x] `ajolopy --version` prints `ajolopy <version>` and exits 0.
- [x] `tests/cli/test_version_flag.py` drives the dispatcher's
      `main(["--version"])` and asserts both the version string and
      the absence of the old usage error.

## Shipped

PR #142 — commit `cd39c41` — released in `v0.1.4`.
