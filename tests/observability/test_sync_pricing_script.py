"""Tests for ``tools/sync_pricing.py``.

Uses canned in-memory fixtures so the suite never touches the network.
Exercises:

- equality path (exit 0, no diff lines),
- drift path (exit 1, diff summary),
- ``--write`` mode rewriting both the snapshot and the recorded SHA.
"""

import json
from pathlib import Path

import pytest

from tools import sync_pricing


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_diff_catalogs_detects_added_removed_changed() -> None:
    embedded = {
        "foo": {"input_cost_per_token": 1.0},
        "bar": {"input_cost_per_token": 2.0},
        "stays": {"input_cost_per_token": 3.0},
    }
    upstream = {
        "stays": {"input_cost_per_token": 3.0},
        "bar": {"input_cost_per_token": 9.9},  # changed
        "new": {"input_cost_per_token": 4.0},  # added
    }
    added, removed, changed = sync_pricing.diff_catalogs(embedded, upstream)
    assert added == ["new"]
    assert removed == ["foo"]
    assert changed == ["bar"]


def test_check_mode_exit_zero_when_in_sync(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = _write(tmp_path / "snapshot.json", {"gpt-4o": {"input_cost_per_token": 1.0}})

    def fake_fetch(_url: str) -> str:
        return snapshot.read_text("utf-8")

    rc = sync_pricing.run(
        mode="check",
        fetcher=fake_fetch,
        snapshot_path=snapshot,
        upstream_url="https://example.invalid",
    )
    assert rc == 0
    captured = capsys.readouterr().out
    assert "up-to-date" in captured


def test_check_mode_exit_non_zero_on_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = _write(tmp_path / "snapshot.json", {"gpt-4o": {"input_cost_per_token": 1.0}})

    def fake_fetch(_url: str) -> str:
        return json.dumps({"gpt-4o": {"input_cost_per_token": 2.5}})

    rc = sync_pricing.run(
        mode="check",
        fetcher=fake_fetch,
        snapshot_path=snapshot,
        upstream_url="https://example.invalid",
    )
    assert rc == 1
    output = capsys.readouterr().out
    assert "Changed models : 1" in output
    assert "~ gpt-4o" in output


def test_write_mode_overwrites_snapshot_and_sha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = _write(tmp_path / "snapshot.json", {"gpt-4o": {"input_cost_per_token": 1.0}})
    sha_source = tmp_path / "sync_pricing_mirror.py"
    sha_source.write_text(
        'LITELLM_UPSTREAM_SHA = "0000000000000000000000000000000000000000"\n',
        encoding="utf-8",
    )

    new_payload = json.dumps({"gpt-4o": {"input_cost_per_token": 2.5}})

    def fake_fetch(_url: str) -> str:
        return new_payload

    rc = sync_pricing.run(
        mode="write",
        fetcher=fake_fetch,
        snapshot_path=snapshot,
        upstream_url="https://example.invalid",
        sha_source=sha_source,
        head_sha="abcd1234abcd1234abcd1234abcd1234abcd1234",
    )
    assert rc == 0
    # Snapshot was rewritten verbatim.
    assert snapshot.read_text("utf-8") == new_payload
    # SHA constant updated.
    rewritten = sha_source.read_text("utf-8")
    assert 'LITELLM_UPSTREAM_SHA = "abcd1234abcd1234abcd1234abcd1234abcd1234"' in rewritten
    output = capsys.readouterr().out
    assert "Wrote refreshed snapshot" in output


def test_replace_sha_constant_raises_when_missing() -> None:
    with pytest.raises(RuntimeError, match="LITELLM_UPSTREAM_SHA"):
        sync_pricing._replace_sha_constant("# no constant here", "abcd1234")


def test_main_dispatches_check_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _write(tmp_path / "snapshot.json", {"gpt-4o": {"input_cost_per_token": 1.0}})
    monkeypatch.setattr(sync_pricing, "SNAPSHOT_PATH", snapshot)

    def _fake_fetch(_url: str) -> str:
        return snapshot.read_text("utf-8")

    monkeypatch.setattr(sync_pricing, "_fetch_upstream", _fake_fetch)
    rc = sync_pricing.main([])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "up-to-date" in captured
