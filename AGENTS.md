# AGENTS.md

Operating manual for any AI coding agent or human contributor working in this
repository. Tool-agnostic — read by Claude Code, Cursor agents, Codex, Aider, and
others. Tool-specific prompts and configs are gitignored.

## Project

**Ajolopy** is a Python framework for building AI-native applications in
production. Strategic context (thesis, wedge user, locked design decisions)
lives in the author's engram memory under `project=ajolopy`. Per-item design
specs live in `specs/<slug>.md`.

## Setup

```bash
uv sync
uv run pre-commit install
```

Requirements: Python 3.14+, `uv`.

## Build / test / lint commands

| Task | Command |
|---|---|
| Run all tests | `uv run pytest` |
| Run a single test | `uv run pytest tests/<path>::<name>` |
| Lint | `uv run ruff check` |
| Lint + auto-fix | `uv run ruff check --fix` |
| Format check | `uv run ruff format --check` |
| Type check | `uv run pyright` |
| Validate the board | `uv run python tools/board.py validate` |

Every PR must keep all of the above green.

## Work tracking — `board.json` is the single source of truth

The project's PM board lives in [`board.json`](./board.json) at the repo root.
Every unit of work — feature, story, fix, chore, refactor, doc change — has an
entry. The schema is enforced by [`.board-schema.json`](./.board-schema.json).
Prose specs live next to the board in [`specs/<slug>.md`](./specs).

### Item statuses

| Status | Meaning |
|---|---|
| `backlog` | Known but not yet groomed — no spec, low detail |
| `ready` | Spec exists, all blockers closed, free to claim |
| `in_progress` | Claimed; owner + branch set |
| `blocked` | Claimed but waiting (see `NOTES` section of the spec) |
| `in_review` | PR is open |
| `done` | Merged to `main` |
| `cancelled` | Abandoned (no longer blocks other items) |

### CLI — `tools/board.py`

Hand-editing `board.json` is discouraged. Use the CLI for atomic, validated
mutations:

```bash
uv run python tools/board.py list                 # board view by status
uv run python tools/board.py list --type fix      # filter by type
uv run python tools/board.py next                 # print id of the next claimable item
uv run python tools/board.py show AJ-1            # item + its spec file
uv run python tools/board.py claim AJ-1           # status=in_progress, set owner+branch, create spec stub if missing
uv run python tools/board.py status AJ-1 in_review
uv run python tools/board.py status AJ-1 done
uv run python tools/board.py add --type fix --slug env-validator-crash \
    --title "env validator crashes on empty .env" --priority p1
uv run python tools/board.py validate             # schema + semantic checks
```

### How to claim a work item

1. `git pull origin main`.
2. `uv run python tools/board.py next` — pick the recommended item, or
   `uv run python tools/board.py list` to choose another `ready` item.
3. `uv run python tools/board.py claim AJ-<n>` — atomically sets
   `status=in_progress`, `owner=<git user.email>`, `branch=<type>/<slug>`,
   and creates `specs/<slug>.md` from a stub if missing.
4. Commit that single board change first: `chore(board): claim AJ-<n>`.
5. Create the feature branch printed by the claim command.
6. Read `specs/<slug>.md`. Pick the first unchecked item under
   `## Acceptance criteria`. Implement it (test-first or test-alongside —
   author's call per item).
7. Open a PR when every acceptance item has at least one passing test.
8. After merge: `uv run python tools/board.py status AJ-<n> done` and commit
   (`chore(board): close AJ-<n>`).

### Multi-agent operation

Multiple agents can work in parallel as long as each holds a **different**
board item. Avoid editing the same `src/ajolopy/<subpath>/` as another
in-progress item without coordinating in the spec's `## Implementation notes`
section.

`board.json` is a single shared file. Concurrent edits cause merge conflicts.
**Rule:** any change to `board.json` must be a small, focused commit (claim,
status transition, add) with `chore(board):` prefix — merge to `main` quickly
so the next agent picks up a fresh state.

When unsure whether your work overlaps with another agent: pause, raise the
question to the author, and wait for direction.

## Code conventions

- Python 3.14+. **Do not** use `from __future__ import annotations` — PEP 649
  is default in 3.14 and the directive hides typing errors at runtime.
- Docstrings, comments, and identifiers in **English**.
- No commented-out code — enforced by ruff rule `ERA`. Use the PR description
  or commit body for historical context.
- Every framework decorator carries full type annotations (`ParamSpec` /
  `TypeVar`). `pyright --strict` must pass.
- Every primitive follows the **"magical default + escape hatch"** pattern.
  A magical-default config (typically a string) covers the 90% case; an escape
  hatch (subclass / callable override) handles the 10%. If a primitive can't
  fit the pattern, surface it to the author rather than violating the rule.

## Commit-message conventions (Conventional Commits)

| Prefix | When |
|---|---|
| `feat(<slug>):` | New capability |
| `fix(<slug>):` | Bug fix |
| `chore(<slug>):` | Deps, CI, build config — no behavior change |
| `chore(board):` | Any change to `board.json` |
| `docs(<slug>):` | Spec / README / AGENTS.md changes |
| `test(<slug>):` | Tests without implementation change |
| `refactor(<slug>):` | Rewrite without behavior change (tests green before + after) |

`<slug>` mirrors the board item's `slug` field. Commits without a board item
(e.g. tooling tweaks) use the relevant area as the scope.

## Hard constraints

- The public primitive surface of v0.1 is fixed at **10 decorators**. The
  complete list lives in `board.json` (items `AJ-1` through `AJ-10`). Adding an
  11th requires explicit author approval before any code is written.
- Commit messages: imperative subject, ~70 chars max, body explains *why*. No
  co-author lines, no AI-tool footers, no mentions of Claude or other agents.
- **Do not push** without explicit author approval.
- **Do not skip pre-commit hooks** (`--no-verify` is forbidden). Fix the
  underlying issue.

## Repository hygiene

- The repository must not contain AI-tool-specific configs or prompts (Cursor
  rules, Claude prompts, Copilot instructions, etc.). `.gitignore` lists the
  patterns. `AGENTS.md` (this file) is the only tool-agnostic exception.

## Security baseline

See [`SECURITY.md`](./SECURITY.md) for the full policy. Quick rules for agents:

- Never commit secrets. `gitleaks` runs as a pre-commit hook.
- Never add a dependency without justifying it in the PR description and
  ensuring it's MIT-compatible with no known CVEs against the pinned version.
- Never relax CI `permissions:` blocks. Default is `contents: read`; widen only
  in the specific job that needs it.
- Never replace pinned commit SHAs with floating tags in workflows. Dependabot
  handles updates.

## Architecture mapping

This repository's harness mirrors the layered architecture shown in
[`docs/architecture.png`](https://github.com — diagram referenced in the
project's strategic docs). Each layer maps to a concrete artifact here:

| Layer | Component in the architecture | Where it lives in this repo |
|---|---|---|
| **Input** | User Interface | `uv`, `pytest`, `ruff`, `pyright`, `tools/board.py`, GitHub Actions |
| | Session Manager (resume/fork/persist) | git branches per board item + engram (`mem_*`) for cross-session memory |
| | Permission Gate (YAML rules, 3 tiers) | CI `permissions:` blocks + pre-commit hooks + GitHub branch protection (`SECURITY.md`) |
| **Knowledge** | Skill Registry (on-demand injection) | `AGENTS.md` + `specs/<slug>.md` — loaded by agents when claiming an item |
| | Context Compressor | engram memory (`mem_save`, `mem_context`) — persistent across sessions |
| | **Task Graph (dependencies + priorities)** | **`board.json` (`blocks` / `blocked_by` + `priority`)** |
| | Memory Store | engram MCP server |
| **Execution** | Tool Dispatch | `pyproject.toml` is the typed registry; each tool is invoked with `uv run` |
| | Streaming Runtime | CI runs jobs in parallel (`board`, `lint`, `typecheck`, `test`, `osv-scanner`, `codeql`, `scorecard`) |
| **Integration** | MCP Runtime | engram is exposed as MCP; future Ajolopy `@MCP` items are tracked on the board |
| | External Servers | filesystem, git |
| **Observability** | Event Bus (Hooks, Lifecycle) | pre-commit hooks + CI events |
| | Background Executor | CI `workflow_dispatch` (manual / scheduled jobs) |
| **Multi-agent** | Subagent Spawner | provided by Claude Code itself (`Task` tool); not part of this repo |
| | **Autonomous Board (self-assign + atomic lock)** | **`board.json` + `tools/board.py claim`** |
| | **FSM Protocol** (IDLE → REQUEST → WAIT → RESPOND) | `ALLOWED_TRANSITIONS` in `tools/board.py`; invalid status edges are rejected |
| | **Worktree Isolator (per-task branch, zero conflicts)** | `tools/board.py claim --worktree` — creates `../ajolopy-<slug>` with `git worktree` |
| **Output** | Task Result (verified output, memory updated) | PR merge → `tools/board.py status AJ-<n> done` → engram `mem_session_summary` |
