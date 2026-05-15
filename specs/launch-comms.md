# AJ-57 — Public v0.1 launch

> Tracked in [`board.json`](../board.json) as `AJ-57`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source-of-truth for the messaging: Brief v4.0 §4 (Killer demo), §5
> (Primitivas core), §6 (Production primitives — los 7 dolores ancla).

## What

The final v0.1 deliverable: the public surface that turns the framework
into a project people find, install, and try. Concretely:

1. **README final** — repo root README that sells v0.1 as a shipping
   product (not pre-alpha), shows the 12-line killer demo, links every
   docs surface that has landed, and includes the install command + a
   row of badges.
2. **HN launch post draft** — Show HN title + body, ready for the
   maintainer to submit.
3. **X / Bluesky launch thread draft** — 10-15 posts, ready to schedule.
4. **Demo video script** — written description of the 60-90 second
   demo. v0.1 ships the **script**; the actual recording is the
   maintainer's task (out of repo scope; flagged as a follow-up).

## Why

The Brief v4.0 calls this "el viral del README" — the first impression
that decides whether the framework gets traction. AJ-57 is the only p0
item left between v0.1 and shipping: AJ-49 (reference docs), AJ-50
(support-agent example), and AJ-54 (docs bot dogfood) all unblocked it
already.

## Public surface

### README final (`README.md`)

Replace the current pre-alpha framing with v0.1-shipping framing.
Structure:

```
# Ajolopy

> The Python framework for building AI-native applications in production.

[badges row: PyPI version, Python versions, license, CI, docs, contributors]

[tagline — one sentence Rails/NestJS analogy]

## Install

pip install ajolopy   # or: uv pip install ajolopy

## The killer demo (12 lines)

[the Step-1 @Agent + @Tool + @Stream snippet, copy-pasteable]

## Why Ajolopy

[short pitch — the 7 production pains list condensed to 5-6 bullets,
links to docs/index.md for the full framing]

## The 10 primitives

[table — fix `@Metric` → drop it (cancelled) or note it's part of @Eval]

## Examples

[support-agent + docsbot — already in current README, keep]

## Where to go next

[Quickstart, Tutorial, Reference, Recipes, contributing — link grid]

## Status

v0.1 — first public release. Active development.

## Contributing

[keep current section]

## License

MIT
```

### Launch comms — `int/launch/v0.1/` (gitignored)

Marketing-facing drafts the maintainer publishes by hand. **These do
NOT ship to GitHub Pages or to the public repo.** They live under
`int/` (gitignored — see `.gitignore`) so reviewers and HN visitors
cannot read the talking-points playbook before the post lands, and so
the public docs site stays focused on user-facing content.

- `int/launch/v0.1/index.md` — overview ("what's in this folder, why").
- `int/launch/v0.1/hn-post.md` — Show HN draft (title + body + reply talking points).
- `int/launch/v0.1/x-thread.md` — X / Bluesky thread (10–15 numbered posts).
- `int/launch/v0.1/demo-video-script.md` — 60–90 second video script (shots, captions, re-record recipe).
- `int/launch/v0.1/demo.cast` — asciinema cast snapshot of the demo flow.

The maintainer keeps these locally (or syncs them via a private
channel — Notion, Google Doc, private repo, whichever fits the team).
Each new release forks a fresh `int/launch/v0.X/` folder so the
playbook iterates over time without leaking past drafts.

### Out of scope

- **Actual demo video recording.** Out of repo scope; flagged as a
  maintainer follow-up.
- **PyPI v0.1.0 release event itself.** AJ-56 shipped the workflow;
  the maintainer cuts the release by tagging `v0.1.0`.
- **Post-launch metrics / dashboards.** Not part of v0.1.
- **Press kit / brand assets.** No logo / image work in v0.1.

## Acceptance criteria

- [x] `README.md` reflects v0.1-shipping state (not pre-alpha).
- [x] `README.md` ships an install command in the first 30 lines.
- [x] `README.md` ships the 12-line killer-demo snippet (Step 1 from
      the AJ-48 tutorial) verbatim.
- [x] `README.md` links to: Quickstart, Tutorial, Reference,
      Observability recipes, Contributing, examples directory.
- [x] `README.md` drops `@Metric` from the 10-primitives table or
      footnotes that it's bundled with `@Eval` (AJ-5 was cancelled
      and rolled into AJ-4).
- [x] `int/launch/v0.1/index.md` overview page (gitignored — local-only).
- [x] `int/launch/v0.1/hn-post.md` — title + body draft ready to paste.
- [x] `int/launch/v0.1/x-thread.md` — 10–15 numbered posts.
- [x] `int/launch/v0.1/demo-video-script.md` — shot list + dialogue +
      timing.
- [x] `int/launch/v0.1/demo.cast` — asciinema snapshot of the demo flow.
- [x] `int/` added to `.gitignore` so launch comms stay off GitHub Pages
      and out of the public repo.
- [x] `uv run --group docs mkdocs build --strict` passes.
- [x] Every internal link in the new docs resolves.
- [x] No mention of "pre-alpha" or "10–16 months" anywhere in
      README / docs / launch comms (v0.1 is here).

## Implementation notes

- The README is the **highest-leverage** artifact. It's worth iterating
  with the maintainer on voice / structure before merging.
- Launch comms drafts are **drafts the maintainer edits and posts** —
  not auto-publishable. Write them so they're ready to paste, not
  ready to ship.
- The video script targets a 60-90 second screen recording of
  `ajolopy new` → `ajolopy dev` → `curl /chat` → eval CI gate. Keep it
  tight.
- The demo recording itself is out of scope. Document the follow-up
  clearly so it doesn't slip.
