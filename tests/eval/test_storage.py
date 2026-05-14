"""Tests for :meth:`EvalRun.save` / :meth:`EvalRun.load`.

Save writes ``schema_version=1`` JSON; load round-trips most fields
verbatim, with the documented exception that ``EvalOutput.raw`` comes
back as the string repr (full fidelity needs the in-memory run).
"""

import json
from pathlib import Path

import pytest

from ajolopy import Agent, Eval, Metric
from ajolopy.eval import EvalRun, EvalRunner
from ajolopy.eval.errors import EvalRunError
from ajolopy.eval.storage import EVAL_RUN_SCHEMA_VERSION
from ajolopy.providers import Response


async def _run_simple(scripted_fake: type, fixtures_dir: Path) -> EvalRun:
    _ = scripted_fake

    @Agent(model="claude-sonnet-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text=f"r{i}", tokens_in=1, tokens_out=1, finish_reason="stop") for i in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"), threshold=0.5)
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    return await EvalRunner().run(_Suite)


@pytest.mark.asyncio
async def test_save_writes_documented_schema(
    scripted_fake: type, fixtures_dir: Path, tmp_path: Path
) -> None:
    run = await _run_simple(scripted_fake, fixtures_dir)
    out = tmp_path / "run.json"
    saved_path = run.save(out)
    assert saved_path == out.resolve()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == EVAL_RUN_SCHEMA_VERSION
    assert payload["suite"] == run.suite
    assert payload["target"]["kind"] == "agent"
    assert payload["target"]["name"] == "Support"
    assert payload["dataset"]["path"] is not None
    assert payload["dataset"]["sha256"] is not None
    assert "metrics" in payload
    assert "cases" in payload
    assert payload["passed"] == run.passed


@pytest.mark.asyncio
async def test_default_save_path_under_dot_ajolopy(
    scripted_fake: type, fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default save location is ``.ajolopy/eval-runs/<ts>.json`` under cwd."""
    monkeypatch.chdir(tmp_path)
    run = await _run_simple(scripted_fake, fixtures_dir)
    saved_path = run.save()
    assert saved_path.parent == (tmp_path / ".ajolopy" / "eval-runs").resolve()
    assert saved_path.exists()


@pytest.mark.asyncio
async def test_timestamp_iso8601_utc(scripted_fake: type, fixtures_dir: Path) -> None:
    run = await _run_simple(scripted_fake, fixtures_dir)
    # The in-memory ``timestamp`` is ISO 8601 UTC with the ``Z`` suffix.
    assert run.timestamp.endswith("Z")
    # The format is ``YYYY-MM-DDTHH:MM:SSZ`` so we can date-parse it.
    from datetime import datetime

    parsed = datetime.fromisoformat(run.timestamp.replace("Z", "+00:00"))
    assert parsed.utcoffset() is not None


@pytest.mark.asyncio
async def test_round_trip_preserves_aggregates(
    scripted_fake: type, fixtures_dir: Path, tmp_path: Path
) -> None:
    run = await _run_simple(scripted_fake, fixtures_dir)
    out = tmp_path / "run.json"
    run.save(out)
    loaded = EvalRun.load(out)
    assert loaded.aggregate_score == pytest.approx(run.aggregate_score)
    assert loaded.passed == run.passed
    assert loaded.metrics["m"].aggregate == pytest.approx(run.metrics["m"].aggregate)
    assert loaded.metrics["m"].passed == run.metrics["m"].passed
    assert len(loaded.cases) == len(run.cases)
    for orig, restored in zip(run.cases, loaded.cases, strict=True):
        assert restored.case_index == orig.case_index
        assert restored.passed == orig.passed
        assert restored.error == orig.error


@pytest.mark.asyncio
async def test_loaded_output_raw_is_string_repr(
    scripted_fake: type, fixtures_dir: Path, tmp_path: Path
) -> None:
    run = await _run_simple(scripted_fake, fixtures_dir)
    out = tmp_path / "run.json"
    run.save(out)
    loaded = EvalRun.load(out)
    assert loaded.cases[0].output is not None
    # The reconstituted ``raw`` is the saved ``repr`` (a string), not
    # the original object — this is the documented limitation.
    assert isinstance(loaded.cases[0].output.raw, str)


def test_schema_version_mismatch_raises(tmp_path: Path) -> None:
    out = tmp_path / "bad.json"
    payload = {
        "schema_version": 999,
        "suite": "x",
        "timestamp": "2026-05-14T00:00:00Z",
        "target": {"kind": "agent", "name": "Y"},
        "dataset": {"path": None, "sha256": None},
        "threshold": 0.5,
        "concurrency": 5,
        "metrics": {},
        "cases": [],
        "aggregate_score": 0.0,
        "passed": False,
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvalRunError, match="unsupported eval-run schema version"):
        EvalRun.load(out)
