"""Persistence for :class:`~ajolopy.eval.results.EvalRun`.

The runner returns the in-memory :class:`EvalRun`; persistence is the
caller's choice via :meth:`EvalRun.save`. The methods bound here keep
:mod:`ajolopy.eval.results` free of :mod:`json` / :mod:`hashlib` /
:mod:`pathlib` imports so the result dataclasses stay import-cheap.

Schema:

- ``schema_version`` is a stable integer (currently ``1``). Any
  on-disk file written by this module carries this number; loaders
  refuse anything else so format drift surfaces immediately.
- The on-disk JSON shape mirrors the dataclass tree with two
  divergences: the per-case ``raw`` value is stored as ``raw_repr``
  (string ``repr``) since arbitrary Python objects are not JSON-safe;
  the dataset block is normalised to ``{"path": ..., "sha256": ...}``.

Round-trip notes:

- :meth:`load` rebuilds the dataclass tree from JSON. The reconstituted
  :class:`~ajolopy.eval.results.EvalOutput.raw` is the saved string
  ``repr`` (not the original object) — the spec documents this
  limitation; clients that need full fidelity should keep the
  in-memory :class:`EvalRun`.
- The default location ``.ajolopy/eval-runs/<timestamp>.json`` is
  created with :meth:`Path.mkdir(parents=True, exist_ok=True)` on
  the first :meth:`save` call.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .errors import EvalRunError
from .results import EvalCaseResult, EvalMetricResult, EvalOutput, EvalRun

__all__ = [
    "DEFAULT_EVAL_RUNS_DIR",
    "EVAL_RUN_SCHEMA_VERSION",
    "load_eval_run",
    "save_eval_run",
]


EVAL_RUN_SCHEMA_VERSION = 1
"""Current on-disk schema version. Bumped on any breaking change."""


DEFAULT_EVAL_RUNS_DIR = Path(".ajolopy") / "eval-runs"
"""Default directory the persistence layer writes runs into.

Resolved against :func:`os.getcwd` at write time; relative paths in
``save()`` calls join below this if no absolute path is supplied."""


def save_eval_run(run: EvalRun, path: str | os.PathLike[str] | None = None) -> Path:
    """Write ``run`` to ``path`` (or the default location) and return the path.

    When ``path`` is ``None``, the file lands at
    ``{cwd}/.ajolopy/eval-runs/{timestamp}.json``. Directory creation
    is idempotent (``mkdir(parents=True, exist_ok=True)``).

    The serialised JSON is human-readable (``indent=2``); large runs
    pay the indentation cost in exchange for diffable PR-attached
    artifacts.
    """
    target = _resolve_save_path(path, run)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _run_to_dict(run)
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return target


def load_eval_run(path: str | os.PathLike[str]) -> EvalRun:
    """Read a previously-written :class:`EvalRun` JSON snapshot.

    Raises :class:`EvalRunError` on a schema-version mismatch. The
    error message names the unsupported version so the caller can
    decide whether to migrate or refuse.
    """
    resolved = Path(os.fspath(path)).resolve()
    payload = cast("dict[str, Any]", json.loads(resolved.read_text(encoding="utf-8")))
    schema_version = payload.get("schema_version")
    if schema_version != EVAL_RUN_SCHEMA_VERSION:
        raise EvalRunError(f"unsupported eval-run schema version {schema_version!r}")
    return _dict_to_run(payload)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_save_path(path: str | os.PathLike[str] | None, run: EvalRun) -> Path:
    # ``run`` is reserved for future per-run-derived filenames (e.g.
    # encoding the suite name); silenced explicitly so unused-arg lint
    # leaves the signature stable for subclasses.
    _ = run
    if path is not None:
        return Path(os.fspath(path)).resolve()
    filename = _timestamp_for_filename() + ".json"
    return (Path.cwd() / DEFAULT_EVAL_RUNS_DIR / filename).resolve()


def _timestamp_for_filename() -> str:
    """POSIX-safe ISO 8601 timestamp for filenames (no colons)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _run_to_dict(run: EvalRun) -> dict[str, Any]:
    return {
        "schema_version": EVAL_RUN_SCHEMA_VERSION,
        "suite": run.suite,
        "timestamp": run.timestamp,
        "target": {"kind": run.target_kind, "name": run.target_name},
        "dataset": {
            "path": run.dataset_path,
            "sha256": run.dataset_sha256,
        },
        "threshold": run.threshold,
        "concurrency": run.concurrency,
        "metrics": {name: _metric_to_dict(metric) for name, metric in run.metrics.items()},
        "cases": [_case_to_dict(case) for case in run.cases],
        "aggregate_score": run.aggregate_score,
        "passed": run.passed,
    }


def _metric_to_dict(metric: EvalMetricResult) -> dict[str, Any]:
    return {
        "aggregator": metric.aggregator,
        "weight": metric.weight,
        "pass_threshold": metric.pass_threshold,
        "values": list(metric.values),
        "aggregate": metric.aggregate,
        "passed": metric.passed,
    }


def _case_to_dict(case: EvalCaseResult) -> dict[str, Any]:
    output: dict[str, Any] | None
    if case.output is None:
        output = None
    else:
        output = {
            "text": case.output.text,
            "latency_ms": case.output.latency_ms,
            "cost_usd": case.output.cost_usd,
            "trace_id": case.output.trace_id,
            "raw_repr": repr(case.output.raw),
        }
    return {
        "case_index": case.case_index,
        "input": dict(case.input),
        "expected": dict(case.expected),
        "output": output,
        "metric_scores": dict(case.metric_scores),
        "error": case.error,
        "passed": case.passed,
    }


def _dict_to_run(payload: dict[str, Any]) -> EvalRun:
    target = cast("dict[str, Any]", payload["target"])
    dataset_block = cast("dict[str, Any]", payload["dataset"])
    metrics_payload = cast("dict[str, dict[str, Any]]", payload["metrics"])
    cases_payload = cast("list[dict[str, Any]]", payload["cases"])

    metrics: dict[str, EvalMetricResult] = {}
    for name, metric_payload in metrics_payload.items():
        values = tuple(float(v) for v in cast("list[Any]", metric_payload["values"]))
        metrics[name] = EvalMetricResult(
            name=name,
            aggregator=cast("str", metric_payload["aggregator"]),
            weight=float(metric_payload["weight"]),
            pass_threshold=float(metric_payload["pass_threshold"]),
            values=values,
            aggregate=float(metric_payload["aggregate"]),
            passed=bool(metric_payload["passed"]),
        )

    cases: list[EvalCaseResult] = []
    for case_payload in cases_payload:
        output_payload = case_payload.get("output")
        output: EvalOutput | None
        if output_payload is None:
            output = None
        else:
            output_dict = cast("dict[str, Any]", output_payload)
            cost_usd = output_dict.get("cost_usd")
            trace_id = output_dict.get("trace_id")
            output = EvalOutput(
                text=cast("str", output_dict["text"]),
                latency_ms=float(output_dict["latency_ms"]),
                cost_usd=float(cost_usd) if cost_usd is not None else None,
                trace_id=cast("str | None", trace_id),
                raw=cast("str", output_dict.get("raw_repr", "")),
            )
        cases.append(
            EvalCaseResult(
                case_index=int(case_payload["case_index"]),
                input=cast("dict[str, Any]", case_payload["input"]),
                expected=cast("dict[str, Any]", case_payload["expected"]),
                output=output,
                metric_scores={
                    k: float(v)
                    for k, v in cast("dict[str, Any]", case_payload["metric_scores"]).items()
                },
                error=cast("str | None", case_payload.get("error")),
                passed=bool(case_payload["passed"]),
            )
        )

    return EvalRun(
        suite=cast("str", payload["suite"]),
        timestamp=cast("str", payload["timestamp"]),
        target_kind=target["kind"],
        target_name=cast("str", target["name"]),
        dataset_path=cast("str | None", dataset_block.get("path")),
        dataset_sha256=cast("str | None", dataset_block.get("sha256")),
        threshold=float(payload["threshold"]),
        concurrency=int(payload["concurrency"]),
        metrics=metrics,
        cases=tuple(sorted(cases, key=lambda c: c.case_index)),
        aggregate_score=float(payload["aggregate_score"]),
        passed=bool(payload["passed"]),
    )


# ---------------------------------------------------------------------------
# Method binders — attach ``save`` / ``load`` to :class:`EvalRun` at import time
# ---------------------------------------------------------------------------


def _save_method(self: EvalRun, path: str | os.PathLike[str] | None = None) -> Path:
    """Write the in-memory :class:`EvalRun` to disk; return the file path."""
    return save_eval_run(self, path)


@classmethod
def _load_classmethod(cls: type[EvalRun], path: str | os.PathLike[str]) -> EvalRun:
    """Read an :class:`EvalRun` JSON snapshot from disk.

    The ``cls`` arg is unused — :class:`EvalRun` has no subclasses that
    would need a polymorphic load. Kept on the class for parity with
    the ``save`` instance method.
    """
    _ = cls
    return load_eval_run(path)


# Bind the methods. The dataclass uses ``slots=True`` so attribute
# assignment on instances is locked; assigning at the class level is
# still permitted and is the standard idiom for late binding.
EvalRun.save = _save_method  # type: ignore[attr-defined]
EvalRun.load = _load_classmethod  # type: ignore[attr-defined]
