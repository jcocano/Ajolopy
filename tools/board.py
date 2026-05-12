"""Ajolopy work-board CLI.

Reads and mutates ``board.json`` at the repository root. Every mutation is
validated against ``.board-schema.json`` (JSON Schema 2020-12) plus a set of
semantic rules: unique ids, no dependency cycles, transitions imply the right
metadata. Writes are atomic (temp file + rename) and the serialized output is
deterministic so diffs stay reviewable.

Run as::

    uv run python tools/board.py <subcommand> [args]

Scaling note
------------
The board is stored as a single ``board.json`` at repo root. This works well
for up to ~3 concurrent contributors / agents touching different items.
Beyond that, the file becomes a merge-conflict hotspot: every ``claim`` and
every ``status`` transition rewrites the same lines.

If concurrent usage grows, migrate to a one-file-per-item layout
(``.work/AJ-1.json``, ``.work/AJ-2.json``, ...) with the same per-item schema
plus a thin ``.work/index.json`` that holds only the dependency graph. Linear,
GitHub Projects, and Jira store work items this way for the same reason.

When that migration happens, the public CLI surface should remain identical;
only the I/O layer below ``load_board``/``save_board`` changes.
"""

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

import jsonschema

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

ROOT: Path = Path(__file__).resolve().parent.parent
BOARD_PATH: Path = ROOT / "board.json"
SCHEMA_PATH: Path = ROOT / ".board-schema.json"
SPECS_DIR: Path = ROOT / "specs"

ItemType = Literal["feature", "story", "fix", "chore", "refactor", "docs"]
ItemStatus = Literal["backlog", "ready", "in_progress", "blocked", "in_review", "done", "cancelled"]
ItemPriority = Literal["p0", "p1", "p2", "p3"]

ITEM_TYPES: tuple[ItemType, ...] = (
    "feature",
    "story",
    "fix",
    "chore",
    "refactor",
    "docs",
)
ITEM_STATUSES: tuple[ItemStatus, ...] = (
    "backlog",
    "ready",
    "in_progress",
    "blocked",
    "in_review",
    "done",
    "cancelled",
)
ITEM_PRIORITIES: tuple[ItemPriority, ...] = ("p0", "p1", "p2", "p3")

# Display order on `list` — keeps active work at the top.
STATUS_DISPLAY_ORDER: tuple[ItemStatus, ...] = (
    "in_progress",
    "in_review",
    "blocked",
    "ready",
    "backlog",
    "done",
    "cancelled",
)

BRANCH_PREFIX: Mapping[ItemType, str] = {
    "feature": "feature",
    "story": "story",
    "fix": "fix",
    "chore": "chore",
    "refactor": "refactor",
    "docs": "docs",
}

# FSM Protocol — allowed status transitions.
# Any other transition is rejected by `cmd_status`. Items always reach `done`
# through `in_progress` → `in_review` so the workflow is enforced uniformly.
ALLOWED_TRANSITIONS: Mapping[ItemStatus, frozenset[ItemStatus]] = {
    "backlog": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"in_progress", "backlog", "cancelled"}),
    "in_progress": frozenset({"blocked", "in_review", "cancelled"}),
    "blocked": frozenset({"in_progress", "cancelled"}),
    "in_review": frozenset({"in_progress", "done", "cancelled"}),
    "done": frozenset(),
    "cancelled": frozenset({"backlog"}),
}


class Item(TypedDict):
    id: str
    slug: str
    type: ItemType
    title: str
    status: ItemStatus
    priority: ItemPriority
    milestone: str | None
    labels: list[str]
    owner: str | None
    branch: str | None
    pr: str | None
    spec: str | None
    blocks: list[str]
    blocked_by: list[str]
    estimate: str | None
    created_at: str
    updated_at: str
    closed_at: str | None


class Board(TypedDict):
    version: int
    updated_at: str
    next_id: int
    items: list[Item]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_board() -> Board:
    raw: dict[str, Any] = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    raw.pop("$schema", None)
    return cast("Board", raw)


def save_board(board: Board) -> None:
    """Validate, then atomically write the board with deterministic ordering."""
    today = date.today().isoformat()
    board["updated_at"] = today
    board["items"] = sorted(board["items"], key=_id_numeric)

    out: dict[str, Any] = {
        "$schema": "./.board-schema.json",
        "version": board["version"],
        "updated_at": board["updated_at"],
        "next_id": board["next_id"],
        "items": [_ordered_item(it) for it in board["items"]],
    }
    validate_board(out)

    tmp = BOARD_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(BOARD_PATH)


def _id_numeric(item: Item) -> int:
    return int(item["id"].split("-")[1])


def _ordered_item(item: Item) -> dict[str, Any]:
    """Return an item dict with predictable key order for stable diffs."""
    return {
        "id": item["id"],
        "slug": item["slug"],
        "type": item["type"],
        "title": item["title"],
        "status": item["status"],
        "priority": item["priority"],
        "milestone": item["milestone"],
        "labels": item["labels"],
        "owner": item["owner"],
        "branch": item["branch"],
        "pr": item["pr"],
        "spec": item["spec"],
        "blocks": item["blocks"],
        "blocked_by": item["blocked_by"],
        "estimate": item["estimate"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "closed_at": item["closed_at"],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_board(raw: dict[str, Any]) -> None:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(raw, schema)

    items: list[dict[str, Any]] = raw["items"]
    ids: set[str] = {it["id"] for it in items}
    if len(ids) != len(items):
        raise ValueError("Duplicate ids in board.json")

    for it in items:
        for dep in it["blocked_by"]:
            if dep not in ids:
                raise ValueError(f"{it['id']}: blocked_by references unknown id {dep}")
        for dep in it["blocks"]:
            if dep not in ids:
                raise ValueError(f"{it['id']}: blocks references unknown id {dep}")

    _detect_cycles(items)
    _check_bidirectional_links(items)


def _detect_cycles(items: list[dict[str, Any]]) -> None:
    by_id: dict[str, dict[str, Any]] = {it["id"]: it for it in items}
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node_id: str, path: list[str]) -> None:
        if node_id in visiting:
            cycle = " → ".join([*path, node_id])
            raise ValueError(f"Dependency cycle: {cycle}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dep in by_id[node_id]["blocked_by"]:
            walk(dep, [*path, node_id])
        visiting.remove(node_id)
        visited.add(node_id)

    for it in items:
        walk(it["id"], [])


def _check_bidirectional_links(items: list[dict[str, Any]]) -> None:
    """If A.blocked_by contains B, then B.blocks must contain A (and vice versa)."""
    by_id: dict[str, dict[str, Any]] = {it["id"]: it for it in items}
    for it in items:
        for dep in it["blocked_by"]:
            if it["id"] not in by_id[dep]["blocks"]:
                raise ValueError(
                    f"{it['id']}.blocked_by includes {dep}, "
                    f"but {dep}.blocks does not include {it['id']}"
                )
        for dep in it["blocks"]:
            if it["id"] not in by_id[dep]["blocked_by"]:
                raise ValueError(
                    f"{it['id']}.blocks includes {dep}, "
                    f"but {dep}.blocked_by does not include {it['id']}"
                )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    board = load_board()
    type_filter: ItemType | None = args.type
    groups: dict[ItemStatus, list[Item]] = {s: [] for s in ITEM_STATUSES}
    for it in board["items"]:
        if type_filter is not None and it["type"] != type_filter:
            continue
        groups[it["status"]].append(it)

    for status in STATUS_DISPLAY_ORDER:
        bucket = groups[status]
        if not bucket:
            continue
        print(f"\n## {status.upper()} ({len(bucket)})")
        for it in sorted(bucket, key=lambda x: (x["priority"], _id_numeric(x))):
            owner = f"  owner=@{it['owner']}" if it["owner"] else ""
            blocked = (
                f"  blocked_by={','.join(it['blocked_by'])}"
                if it["blocked_by"] and status not in ("done", "cancelled")
                else ""
            )
            print(f"  {it['id']:<6} [{it['priority']}] {it['title']}{owner}{blocked}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    board = load_board()
    item = _find(board, args.id)
    print(json.dumps(_ordered_item(item), indent=2, ensure_ascii=False))
    if item["spec"]:
        spec_path = ROOT / item["spec"]
        if spec_path.exists():
            print(f"\n--- {item['spec']} ---\n")
            print(spec_path.read_text(encoding="utf-8"))
        else:
            print(f"\n[spec file {item['spec']} not found]")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    del args
    board = load_board()
    closed_ids = {it["id"] for it in board["items"] if it["status"] in ("done", "cancelled")}
    eligible = [
        it
        for it in board["items"]
        if it["status"] == "ready" and not (set(it["blocked_by"]) - closed_ids)
    ]
    if not eligible:
        print("No ready items unblocked. Use `list` to see the full board.")
        return 1
    nxt = sorted(eligible, key=lambda x: (x["priority"], _id_numeric(x)))[0]
    print(nxt["id"])
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    board = load_board()
    item = _find(board, args.id)

    if item["status"] == "in_progress":
        print(f"{item['id']} already in_progress (owner={item['owner']})")
        return 1
    if item["status"] != "ready":
        print(f"{item['id']} is '{item['status']}', must be 'ready' to claim")
        return 1

    closed_ids = {it["id"] for it in board["items"] if it["status"] in ("done", "cancelled")}
    blocking = set(item["blocked_by"]) - closed_ids
    if blocking:
        print(f"{item['id']} is blocked by undone items: {sorted(blocking)}")
        return 1

    owner: str = args.owner or _git_user()
    if not owner:
        print("Could not determine owner. Pass --owner or set git config user.email.")
        return 1
    branch = f"{BRANCH_PREFIX[item['type']]}/{item['slug']}"

    if not item["spec"]:
        spec_rel = _ensure_spec_stub(item)
        item["spec"] = spec_rel

    item["status"] = "in_progress"
    item["owner"] = owner
    item["branch"] = branch
    item["updated_at"] = date.today().isoformat()
    save_board(board)
    print(f"Claimed {item['id']} → branch {branch} (owner={owner}, spec={item['spec']})")

    if args.worktree:
        wt_path = _create_worktree(item["slug"], branch)
        if wt_path is None:
            return 1
        print(f"  Worktree: {wt_path}")
        print(f"  cd {wt_path}")
    else:
        print(f"  Next: git checkout -b {branch}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    board = load_board()
    item = _find(board, args.id)
    new_status: ItemStatus = args.new

    current = item["status"]
    allowed = ALLOWED_TRANSITIONS[current]
    if new_status == current:
        print(f"{item['id']} already in '{current}' — no change")
        return 0
    if new_status not in allowed:
        print(f"Invalid transition: {current} → {new_status}")
        print(f"  Allowed from '{current}': {sorted(allowed) or '(terminal)'}")
        return 1

    today = date.today().isoformat()
    item["status"] = new_status
    item["updated_at"] = today
    if new_status in ("done", "cancelled"):
        item["closed_at"] = today
    save_board(board)
    print(f"{item['id']} → {new_status}")

    if new_status in ("done", "cancelled") and item["branch"]:
        wt_path = ROOT.parent / f"ajolopy-{item['slug']}"
        if wt_path.exists():
            print(f"  Worktree at {wt_path} can now be removed:")
            print(f"    git worktree remove {wt_path}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    del args
    raw: dict[str, Any] = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    validate_board(raw)
    print("board.json is valid")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    board = load_board()
    new_id = f"AJ-{board['next_id']}"
    board["next_id"] += 1
    today = date.today().isoformat()

    blocked_by: list[str] = (
        [s.strip() for s in args.blocked_by.split(",") if s.strip()] if args.blocked_by else []
    )
    labels: list[str] = (
        [s.strip() for s in args.labels.split(",") if s.strip()] if args.labels else []
    )

    item: Item = {
        "id": new_id,
        "slug": args.slug,
        "type": args.type,
        "title": args.title,
        "status": "backlog",
        "priority": args.priority,
        "milestone": args.milestone,
        "labels": labels,
        "owner": None,
        "branch": None,
        "pr": None,
        "spec": None,
        "blocks": [],
        "blocked_by": blocked_by,
        "estimate": None,
        "created_at": today,
        "updated_at": today,
        "closed_at": None,
    }
    board["items"].append(item)

    if blocked_by:
        by_id = {it["id"]: it for it in board["items"]}
        for dep in blocked_by:
            if dep not in by_id:
                raise SystemExit(f"unknown blocked_by id: {dep}")
            if new_id not in by_id[dep]["blocks"]:
                by_id[dep]["blocks"].append(new_id)
                by_id[dep]["blocks"].sort(key=lambda x: int(x.split("-")[1]))

    save_board(board)
    print(f"Added {new_id} ({item['type']}): {item['title']}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find(board: Board, item_id: str) -> Item:
    for it in board["items"]:
        if it["id"] == item_id:
            return it
    raise SystemExit(f"unknown id: {item_id}")


def _git_user() -> str:
    try:
        return subprocess.check_output(
            ["git", "config", "user.email"],
            text=True,
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return ""


def _ensure_spec_stub(item: Item) -> str:
    SPECS_DIR.mkdir(exist_ok=True)
    spec_path = SPECS_DIR / f"{item['slug']}.md"
    if not spec_path.exists():
        spec_path.write_text(_spec_template(item), encoding="utf-8")
    return f"specs/{item['slug']}.md"


def _create_worktree(slug: str, branch: str) -> Path | None:
    """Create a sister-directory git worktree on a fresh branch.

    The path is derived purely from the slug so two machines never disagree.
    Branch is created from the current HEAD (caller is expected to be on
    a clean ``main``).
    """
    wt_path = ROOT.parent / f"ajolopy-{slug}"
    if wt_path.exists():
        print(f"Worktree path {wt_path} already exists; skipping.")
        return wt_path
    try:
        subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        print(f"Failed to create worktree: {stderr.strip() or exc}")
        return None
    except FileNotFoundError:
        print("git not found on PATH; cannot create worktree.")
        return None
    return wt_path


def _spec_template(item: Item) -> str:
    return (
        f"# {item['id']} — {item['title']}\n\n"
        f"> Tracked in [`board.json`](../board.json) as `{item['id']}`. Status, "
        f"owner, branch, and dependencies live there.\n\n"
        "## What\n\nTBD\n\n"
        "## Why\n\nTBD\n\n"
        "## Design rule\n\n"
        "Follow the framework-wide **magical default + escape hatch** pattern. "
        "Document the specifics for this item below.\n\n"
        "## Acceptance criteria\n\n"
        "- [ ] TBD — replace with concrete, testable items.\n\n"
        "## Implementation pointers\n\n"
        f"- Source: `src/ajolopy/{item['slug']}/` (TBD)\n"
        f"- Tests: `tests/{item['slug']}/` (TBD)\n\n"
        "## Implementation notes\n\n"
        "Empty for now. Append entries during the work in chronological order "
        "with a `YYYY-MM-DD` prefix.\n"
    )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="board", description="Ajolopy work-board CLI.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list board grouped by status")
    p_list.add_argument("--type", choices=list(ITEM_TYPES), default=None)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one item plus its spec")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_next = sub.add_parser("next", help="print the id of the next claimable item")
    p_next.set_defaults(func=cmd_next)

    p_claim = sub.add_parser(
        "claim",
        help="claim an item (status=in_progress, owner, branch). Creates a spec stub if missing.",
    )
    p_claim.add_argument("id")
    p_claim.add_argument("--owner", default=None)
    p_claim.add_argument(
        "--worktree",
        action="store_true",
        help="also create a git worktree at ../ajolopy-<slug> on the new branch",
    )
    p_claim.set_defaults(func=cmd_claim)

    p_status = sub.add_parser("status", help="transition an item's status")
    p_status.add_argument("id")
    p_status.add_argument("new", choices=list(ITEM_STATUSES))
    p_status.set_defaults(func=cmd_status)

    p_add = sub.add_parser("add", help="add a new item to the backlog")
    p_add.add_argument("--type", required=True, choices=list(ITEM_TYPES))
    p_add.add_argument("--slug", required=True)
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--priority", default="p2", choices=list(ITEM_PRIORITIES))
    p_add.add_argument("--milestone", default=None)
    p_add.add_argument("--labels", default="")
    p_add.add_argument("--blocked-by", dest="blocked_by", default="")
    p_add.set_defaults(func=cmd_add)

    p_validate = sub.add_parser(
        "validate", help="validate board.json against schema + semantic rules"
    )
    p_validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
