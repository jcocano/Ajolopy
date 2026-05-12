"""Tests for the work-board CLI tooling.

These exercise the helpers and the CLI entry directly (no subprocess) so
coverage and pyright apply.
"""

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from tools import board

# ---------------------------------------------------------------------------
# Fixtures and factories
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(board.__file__).resolve().parent.parent


def _make_item(**overrides: Any) -> board.Item:
    base: dict[str, Any] = {
        "id": "AJ-1",
        "slug": "test",
        "type": "feature",
        "title": "Test item",
        "status": "backlog",
        "priority": "p1",
        "milestone": "v0.1",
        "labels": [],
        "owner": None,
        "branch": None,
        "pr": None,
        "spec": None,
        "blocks": [],
        "blocked_by": [],
        "estimate": None,
        "created_at": "2026-05-12",
        "updated_at": "2026-05-12",
        "closed_at": None,
    }
    base.update(overrides)
    return cast("board.Item", base)


def _make_board_dict(items: list[board.Item]) -> dict[str, Any]:
    return {
        "$schema": "./.board-schema.json",
        "version": 1,
        "updated_at": "2026-05-12",
        "next_id": len(items) + 1,
        "items": [dict(it) for it in items],
    }


@pytest.fixture
def isolated_board(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect ROOT/BOARD_PATH/SCHEMA_PATH/SPECS_DIR to a tmp dir."""
    schema_src = _REPO_ROOT / ".board-schema.json"
    schema_dst = tmp_path / ".board-schema.json"
    schema_dst.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(board, "ROOT", tmp_path)
    monkeypatch.setattr(board, "BOARD_PATH", tmp_path / "board.json")
    monkeypatch.setattr(board, "SCHEMA_PATH", schema_dst)
    monkeypatch.setattr(board, "SPECS_DIR", tmp_path / "specs")
    return tmp_path


def _write_board(data: dict[str, Any]) -> None:
    board.BOARD_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_valid_board_passes(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item()])
        board.validate_board(data)

    def test_unknown_status_fails(self, isolated_board: Path) -> None:
        item = _make_item()
        raw = dict(item)
        raw["status"] = "invalid_status"
        data = _make_board_dict([cast("board.Item", raw)])
        with pytest.raises(jsonschema.ValidationError):
            board.validate_board(data)

    def test_bad_slug_fails(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(slug="UPPERCASE")])
        with pytest.raises(jsonschema.ValidationError):
            board.validate_board(data)

    def test_bad_id_fails(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(id="X-1")])
        with pytest.raises(jsonschema.ValidationError):
            board.validate_board(data)

    def test_in_progress_requires_owner(self, isolated_board: Path) -> None:
        data = _make_board_dict(
            [
                _make_item(
                    status="in_progress",
                    owner=None,
                    branch="feature/test",
                    spec="specs/test.md",
                )
            ]
        )
        with pytest.raises(jsonschema.ValidationError):
            board.validate_board(data)

    def test_done_requires_closed_at(self, isolated_board: Path) -> None:
        data = _make_board_dict(
            [
                _make_item(
                    status="done",
                    owner="x",
                    branch="feature/test",
                    spec="specs/test.md",
                    closed_at=None,
                )
            ]
        )
        with pytest.raises(jsonschema.ValidationError):
            board.validate_board(data)

    def test_ready_requires_spec(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(status="ready", spec=None)])
        with pytest.raises(jsonschema.ValidationError):
            board.validate_board(data)


# ---------------------------------------------------------------------------
# Semantic validation
# ---------------------------------------------------------------------------


class TestSemanticValidation:
    def test_duplicate_ids_fails(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(id="AJ-1"), _make_item(id="AJ-1", slug="other")])
        with pytest.raises(ValueError, match="Duplicate ids"):
            board.validate_board(data)

    def test_unknown_blocked_by_fails(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(blocked_by=["AJ-999"])])
        with pytest.raises(ValueError, match="unknown id"):
            board.validate_board(data)

    def test_unknown_blocks_fails(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(blocks=["AJ-999"])])
        with pytest.raises(ValueError, match="unknown id"):
            board.validate_board(data)

    def test_cycle_two_node_fails(self, isolated_board: Path) -> None:
        data = _make_board_dict(
            [
                _make_item(id="AJ-1", slug="a", blocks=["AJ-2"], blocked_by=["AJ-2"]),
                _make_item(id="AJ-2", slug="b", blocks=["AJ-1"], blocked_by=["AJ-1"]),
            ]
        )
        with pytest.raises(ValueError, match="cycle"):
            board.validate_board(data)

    def test_bidirectional_mismatch_fails(self, isolated_board: Path) -> None:
        # AJ-1.blocked_by = [AJ-2], but AJ-2.blocks does not include AJ-1.
        data = _make_board_dict(
            [
                _make_item(id="AJ-1", slug="a", blocked_by=["AJ-2"]),
                _make_item(id="AJ-2", slug="b"),
            ]
        )
        with pytest.raises(ValueError, match="does not include"):
            board.validate_board(data)


# ---------------------------------------------------------------------------
# FSM transitions
# ---------------------------------------------------------------------------


class TestFSMTransitions:
    @pytest.mark.parametrize(
        ("frm", "to"),
        [
            ("backlog", "ready"),
            ("backlog", "cancelled"),
            ("ready", "in_progress"),
            ("ready", "backlog"),
            ("ready", "cancelled"),
            ("in_progress", "in_review"),
            ("in_progress", "blocked"),
            ("in_progress", "cancelled"),
            ("blocked", "in_progress"),
            ("blocked", "cancelled"),
            ("in_review", "done"),
            ("in_review", "in_progress"),
            ("in_review", "cancelled"),
            ("cancelled", "backlog"),
        ],
    )
    def test_valid_edges(self, frm: board.ItemStatus, to: board.ItemStatus) -> None:
        assert to in board.ALLOWED_TRANSITIONS[frm]

    @pytest.mark.parametrize(
        ("frm", "to"),
        [
            ("backlog", "in_progress"),
            ("backlog", "done"),
            ("ready", "done"),
            ("ready", "blocked"),
            ("in_progress", "done"),
            ("done", "in_progress"),
            ("done", "cancelled"),
            ("cancelled", "in_progress"),
        ],
    )
    def test_invalid_edges(self, frm: board.ItemStatus, to: board.ItemStatus) -> None:
        assert to not in board.ALLOWED_TRANSITIONS[frm]

    def test_done_is_terminal(self) -> None:
        assert board.ALLOWED_TRANSITIONS["done"] == frozenset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_id_numeric_extracts_integer(self) -> None:
        assert board._id_numeric(_make_item(id="AJ-42")) == 42

    def test_ordered_item_preserves_data(self) -> None:
        item = _make_item(id="AJ-7", slug="lucky")
        ordered = board._ordered_item(item)
        assert ordered["id"] == "AJ-7"
        assert ordered["slug"] == "lucky"
        keys = list(ordered.keys())
        assert keys[0] == "id"
        assert keys[-1] == "closed_at"

    def test_spec_template_uses_slug_and_id(self) -> None:
        item = _make_item(id="AJ-9", slug="agent", title="@Agent decorator")
        out = board._spec_template(item)
        assert "AJ-9" in out
        assert "@Agent decorator" in out
        assert "src/ajolopy/agent/" in out
        assert "tests/agent/" in out


# ---------------------------------------------------------------------------
# I/O round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_save_then_load(self, isolated_board: Path) -> None:
        original = _make_board_dict([_make_item(id="AJ-3", slug="three")])
        board.save_board(cast("board.Board", original))
        loaded = board.load_board()
        assert len(loaded["items"]) == 1
        assert loaded["items"][0]["id"] == "AJ-3"
        assert loaded["items"][0]["slug"] == "three"

    def test_save_sorts_items_by_numeric_id(self, isolated_board: Path) -> None:
        data = _make_board_dict(
            [
                _make_item(id="AJ-5", slug="five"),
                _make_item(id="AJ-2", slug="two"),
                _make_item(id="AJ-10", slug="ten"),
            ]
        )
        board.save_board(cast("board.Board", data))
        raw = json.loads(board.BOARD_PATH.read_text(encoding="utf-8"))
        ids = [it["id"] for it in raw["items"]]
        assert ids == ["AJ-2", "AJ-5", "AJ-10"]

    def test_save_emits_schema_reference(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item()])
        board.save_board(cast("board.Board", data))
        raw = json.loads(board.BOARD_PATH.read_text(encoding="utf-8"))
        assert raw["$schema"] == "./.board-schema.json"


# ---------------------------------------------------------------------------
# CLI smoke (via main())
# ---------------------------------------------------------------------------


class TestCLI:
    def test_validate_ok(self, isolated_board: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_board(_make_board_dict([_make_item()]))
        rc = board.main(["validate"])
        assert rc == 0
        assert "valid" in capsys.readouterr().out

    def test_validate_rejects_bad_schema(self, isolated_board: Path) -> None:
        data = _make_board_dict([_make_item(slug="BAD-Slug")])
        _write_board(data)
        with pytest.raises(jsonschema.ValidationError):
            board.main(["validate"])

    def test_status_rejects_invalid_transition(
        self, isolated_board: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_board(_make_board_dict([_make_item(status="backlog")]))
        rc = board.main(["status", "AJ-1", "done"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "Invalid transition" in out

    def test_status_same_status_is_noop(
        self, isolated_board: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_board(_make_board_dict([_make_item(status="backlog")]))
        rc = board.main(["status", "AJ-1", "backlog"])
        assert rc == 0
        assert "no change" in capsys.readouterr().out

    def test_next_returns_ready_unblocked(
        self, isolated_board: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_board(
            _make_board_dict(
                [
                    _make_item(
                        id="AJ-1",
                        slug="a",
                        status="ready",
                        priority="p0",
                        spec="specs/a.md",
                    ),
                    _make_item(id="AJ-2", slug="b", priority="p0"),
                ]
            )
        )
        rc = board.main(["next"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "AJ-1"

    def test_next_skips_blocked_items(
        self, isolated_board: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_board(
            _make_board_dict(
                [
                    _make_item(
                        id="AJ-1",
                        slug="a",
                        status="ready",
                        priority="p0",
                        spec="specs/a.md",
                        blocked_by=["AJ-2"],
                        blocks=[],
                    ),
                    _make_item(
                        id="AJ-2",
                        slug="b",
                        status="backlog",
                        priority="p1",
                        blocks=["AJ-1"],
                    ),
                ]
            )
        )
        rc = board.main(["next"])
        assert rc == 1
        assert "No ready items unblocked" in capsys.readouterr().out

    def test_add_inserts_item_with_bidirectional_blocks(
        self, isolated_board: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_board(
            _make_board_dict(
                [_make_item(id="AJ-1", slug="parent", status="ready", spec="specs/parent.md")]
            )
        )
        rc = board.main(
            [
                "add",
                "--type",
                "story",
                "--slug",
                "child",
                "--title",
                "Child story",
                "--priority",
                "p1",
                "--blocked-by",
                "AJ-1",
            ]
        )
        assert rc == 0
        loaded = board.load_board()
        new = next(it for it in loaded["items"] if it["slug"] == "child")
        parent = next(it for it in loaded["items"] if it["slug"] == "parent")
        assert new["blocked_by"] == ["AJ-1"]
        assert parent["blocks"] == [new["id"]]
        assert "Added" in capsys.readouterr().out
