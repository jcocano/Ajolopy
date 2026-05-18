# AJ-78 — Rebuild docsbot RAG corpus so it stops citing `claude-sonnet-4-7`

> Tracked in [`board.json`](../board.json) as `AJ-78`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Type: `fix` (stale data artifact, post-launch). Milestone: post-v0.1.

## What

Regenerate `dogfood/docsbot/data/docs-index.jsonl` against the current
`docs/` tree so the RAG corpus stops citing the unreleased
`claude-sonnet-4-7` model. The string appears in 15 snippets across
`quickstart.md`, `reference/agent.md`, `reference/eval.md`,
`reference/mcp.md`, `reference/stream.md`, `reference/tool.md`,
`reference/workflow.md`, `tutorial/step-1-hello.md`,
`tutorial/step-2-evals.md`, and `tutorial/step-3-team.md`.

## Why

The v0.1.1 release (`ded9016`) replaced `claude-sonnet-4-7` →
`claude-opus-4-7` repo-wide across `README.md`, `docs/`, `examples/`,
`dogfood/`, `specs/`, and `tests/`. The docs sources are clean. The
docsbot's RAG corpus snapshot, however, was indexed against the docs
*before* the rewrite landed and never got rebuilt. The bot still
retrieves and quotes the old snippets verbatim.

Surface impact:

- A visitor who lands on the docsbot from the README or a future HN
  post asks "show me how to use `@Agent`" or "what model does the
  quickstart use" — the bot answers with `model="claude-sonnet-4-7"`,
  a string that fails at first invocation.
- The dogfood story ("Ajolopy uses Ajolopy to power its own docs bot")
  is undermined the moment someone notices the bot disagrees with the
  docs site it claims to mirror.

This is **a stale-data artifact, not a string-rewrite bug**. The
docsbot has a corpus-build step; the right fix is to re-run that step,
not to find-and-replace inside the JSONL.

## Out of scope

- Touching the docs themselves (already clean).
- Touching `src/ajolopy/cli/commands/_templates/` (closed by #133).
- Touching `int/launch/v0.1/hn-post.md` (local launch draft; the
  maintainer fixes that before submitting).
- Bumping `dogfood/docsbot/`'s own version or dependency pins. The
  corpus rebuild should be a no-op for the package surface.

## Acceptance criteria

- [ ] `git grep "claude-sonnet-4-7" dogfood/docsbot/data/` returns no
      matches.
- [ ] Every snippet in the rebuilt `docs-index.jsonl` round-trips back
      to a line range that exists in the current `docs/` source — i.e.
      the corpus is a faithful snapshot of `docs/` at the rebuild
      commit, not a partial replace.
- [ ] The docsbot's existing test suite (`dogfood/docsbot/tests/`)
      stays green.
- [ ] If the rebuild process is not yet automated, document the
      manual recipe in `dogfood/docsbot/README.md` (or wherever the
      operator docs live) so the next person can re-run it without
      reverse-engineering the script. Single paragraph is fine.

## Implementation pointers

1. Locate the corpus-build script under `dogfood/docsbot/` (likely
   `dogfood/docsbot/scripts/` or invoked via a `scripts.build_index`
   entry). If none exists, the corpus is hand-curated — file a
   follow-up to automate it before doing this fix manually.
2. Run the rebuild script against the current `docs/` tree.
3. Diff the new JSONL against the existing one: expect changes only in
   model strings and possibly some line offsets if the docs were
   reflowed. Significant content changes outside model strings would
   mean the docs were rewritten more than expected — surface in the PR
   description so reviewers know.
4. Re-run the docsbot suite locally and commit.

## Long-term follow-up (out of scope, worth tracking separately)

The corpus rebuild should ideally be wired into CI on `docs/` changes
so this class of drift cannot recur. That is its own item — file as a
chore against the docsbot once this fix lands.

## Implementation notes

<!-- Filled when this item ships. Record the rebuild command run, any
docs that surprised you, and whether the automation follow-up has been
filed. -->
