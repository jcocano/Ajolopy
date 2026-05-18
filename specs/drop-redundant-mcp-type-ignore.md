# AJ-77 — Drop redundant `# type: ignore[import-not-found]` on the `mcp` import

> Tracked in [`board.json`](../board.json) as `AJ-77`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Type: `chore` (typing hygiene). Milestone: post-v0.1.

## What

Resolve the `reportUnnecessaryTypeIgnoreComment` warning that pyright reports
on `src/ajolopy/mcp/client.py:113`:

```python
def _load_mcp() -> Any:
    try:
        import mcp  # type: ignore[import-not-found]  # optional extra, guarded at call time
    except ImportError as exc:
        raise MCPDependencyError(_DEPENDENCY_HINT) from exc
    return mcp
```

In the CI / release pre-flight footprint (`uv sync --extra mcp ...`), pyright
resolves the `mcp` import without trouble, so the `# type: ignore` is
**redundant** and the strict checker flags it as a warning.

In a minimal-install footprint (`uv sync` without `--extra mcp`), pyright
would fail on the same line because the module is missing — that is exactly
what the comment was added to silence. The two footprints contradict each
other; the current comment fits only one of them.

## Why

`reportUnnecessaryTypeIgnoreComment = "warning"` is set explicitly in
`pyproject.toml` (line 201). It does not break CI today (only errors do),
so the release pipeline does not fail. But:

- Every `uv run pyright` invocation prints a noisy `1 warning` line, which
  trains the team to ignore pyright output.
- Future strict-mode promotions could turn this warning into an error
  without warning, breaking the release pipeline on a stale comment.

This is small typing debt that gets cleaner the sooner it lands. Kept out
of the v0.1.2 release diff on purpose — release PR scope was strictly
"Dependabot bumps + sync_pricing test fix".

## Approach

Three viable fixes, ranked:

1. **Replace with pyright's own ignore (recommended).**
   ```python
   import mcp  # pyright: ignore[reportMissingImports]  # optional extra, guarded at call time
   ```
   Pyright treats its own `# pyright: ignore[...]` directives as
   intentional even when they happen to be unnecessary on the current
   resolution path — no `reportUnnecessaryTypeIgnoreComment` warning in
   the full-extras footprint, and the suppression still works in the
   minimal footprint. Covers both install matrices with one comment.

2. **Drop the comment entirely.** Works only because every documented
   path that runs pyright (CI + the recommended dev `uv sync --extra ...`
   incantation in `CLAUDE.md`) installs the `mcp` extra. A developer who
   diverges from that — runs pyright after a bare `uv sync` — would hit
   an error. Acceptable but fragile.

3. **Refactor the import to avoid pyright seeing it at all.** Wrap with
   `importlib.import_module("mcp")` and `cast("Any", ...)`. Removes the
   need for any comment but trades one form of ceremony for another and
   loses static analysis on the SDK boundary. Don't take this unless 1
   and 2 both prove insufficient.

## Out of scope

- Changing how the `mcp` extra is declared (still `mcp = ["mcp>=1.0.0"]`
  in `pyproject.toml`).
- Touching the other optional-extra import guards (`redis`, `postgres`,
  `mongo`, `qdrant`, `pgvector` in `memory/` and `rag/`) unless an
  identical pattern bites them — review separately, do not bundle.
- Promoting `reportUnnecessaryTypeIgnoreComment` from `warning` to
  `error` repo-wide. That is its own decision, not implied by this
  cleanup.

## Acceptance criteria

- [ ] `src/ajolopy/mcp/client.py:113` no longer triggers
      `reportUnnecessaryTypeIgnoreComment` under the full-extras CI
      pyright invocation.
- [ ] `uv run pyright` reports no errors and no warnings for the
      `mcp/` package — or, if other unrelated warnings remain, the
      total warning count drops by exactly the one this item targets.
- [ ] The existing test suite (`tests/mcp/`) stays green without
      modification — this is a typing-only change, no behavioural
      impact.
- [ ] `uv run ruff check` / `ruff format --check` clean.
- [ ] If approach 1 is chosen, the inline comment still names the
      reason (`optional extra, guarded at call time`) so future readers
      do not delete it as cruft.

## Implementation pointers

- Single file edit: `src/ajolopy/mcp/client.py:113`.
- Verify locally with both footprints if you want to be exhaustive:
  - Full extras (CI default): `uv sync --extra mcp ...` then `uv run pyright src/ajolopy/mcp/`.
  - Minimal: `uv sync` (no extras) then `uv run pyright src/ajolopy/mcp/`
    — should also be clean with approach 1.

## Implementation notes

<!-- Filled when this item ships. Record which approach was taken and
why, plus the pyright version against which the warning disappeared. -->
