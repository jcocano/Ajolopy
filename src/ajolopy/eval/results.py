"""Result dataclasses produced by :class:`~ajolopy.eval.runner.EvalRunner`.

Every dataclass is :class:`frozen=True` and :class:`slots=True`:

- ``frozen=True`` so metrics, post-processing, or reporting code cannot
  accidentally mutate a result mid-pipeline. Reuses the same contract
  :class:`~ajolopy.eval.case.Case` enforces on the dataset side.
- ``slots=True`` keeps construction cheap. A large suite produces one
  :class:`EvalCaseResult` per case plus one :class:`EvalMetricResult`
  per metric; for a 1000-case suite with 4 metrics that is 1004 small
  dataclasses per run.

The runner builds these in order:

1. One :class:`EvalOutput` per case from ``target.run(**case.input)``.
2. One :class:`EvalCaseResult` per case wrapping the output + metric
   scores + pass/fail.
3. One :class:`EvalMetricResult` per ``@Metric`` aggregating the
   per-case values via its configured aggregator.
4. One :class:`EvalRun` rolling everything up, ready to be returned
   from :meth:`~ajolopy.eval.runner.EvalRunner.run` or persisted via
   :meth:`EvalRun.save`.

Comparison-side types (:class:`MetricDelta`, :class:`EvalComparison`)
live here too so the public surface ships a single result module.
``save`` and ``load`` are deliberately not method stubs on
:class:`EvalRun` — the I/O lives in :mod:`ajolopy.eval.storage` and is
bound onto the class by the package ``__init__`` to keep this module
import-cheap (no :mod:`json` / :mod:`hashlib` here).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import os
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "EvalCaseResult",
    "EvalComparison",
    "EvalMetricResult",
    "EvalOutput",
    "EvalRun",
    "MetricDelta",
    "bind_persistence",
]


# Persistence callables bound at package init time by ``ajolopy.eval.__init__``
# to break what would otherwise be a ``results <-> storage`` import cycle
# (CodeQL flags the lazy in-method imports as cyclic). ``storage.py``
# unconditionally imports the dataclasses defined here; this module never
# imports ``storage`` — instead :meth:`EvalRun.save` / :meth:`EvalRun.load`
# dispatch through these slots, which :func:`bind_persistence` populates.
# Slots are typed ``Any`` (and named lower-case) so pyright treats them as
# mutable variables rather than constants the binder is forbidden to touch.
_save_eval_run: Any = None
_load_eval_run: Any = None


def bind_persistence(save_fn: Any, load_fn: Any) -> None:
    """Register the storage-layer implementations of save/load.

    Called once at :mod:`ajolopy.eval` import time. The indirection
    keeps this module free of any :mod:`ajolopy.eval.storage` import
    (avoids a CodeQL-flagged cyclic import) while still letting
    :meth:`EvalRun.save` / :meth:`EvalRun.load` behave like ordinary
    methods to consumers. ``save_fn`` / ``load_fn`` are typed ``Any``
    here because exposing the real signatures would force importing
    :class:`~pathlib.Path` plus the ``Callable`` generic into runtime
    scope just to satisfy annotations — the public surface
    (``EvalRun.save`` / ``EvalRun.load``) keeps its typed signature.
    """
    global _save_eval_run, _load_eval_run
    _save_eval_run = save_fn
    _load_eval_run = load_fn


@dataclass(slots=True, frozen=True)
class EvalOutput:
    """One snapshot of ``target.run(**case.input)`` plus its context.

    ``text`` is always a string — non-string returns are coerced via
    :func:`str` and the original value is preserved on :attr:`raw` so
    metrics that need typed access (e.g. counting tool calls on a
    workflow result) can cast without re-parsing the text.

    ``cost_usd`` is the sum of the chat-span costs collected by the
    runner via the ``cost_sink`` kwarg on :class:`AgentRuntime.run`.
    It is ``None`` when every chat span had an unknown model (the
    pricing layer returns ``None`` per span) OR when the target is a
    workflow (cost rollup over workflow targets is left to AJ-31's
    deeper instrumentation).

    ``trace_id`` is the 32-char hex form of the current OTel span's
    trace id, formatted from
    :meth:`opentelemetry.trace.SpanContext.trace_id`. ``None`` when
    the active span has no valid context (e.g. no SDK installed).

    ``tool_calls`` carries the names of tools the agent dispatched
    during the case in call order. Populated by the runner via the
    ``AgentRuntime.run(tool_calls_sink=...)`` orchestrator hook
    (AJ-26). Defaults to ``()`` for workflow targets, custom datasets,
    and any code path that pre-dates the field — the default keeps
    every existing call site working.
    """

    text: str
    latency_ms: float
    cost_usd: float | None
    trace_id: str | None
    raw: object
    tool_calls: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class EvalCaseResult:
    """One case's result: output + per-metric scores + pass/fail.

    ``passed`` is the conjunction of "no error" AND every metric's
    per-case threshold check (``score >= metric.pass_threshold``). The
    runner sets ``passed=False`` whenever ``error is not None`` even if
    the partial metric scores would otherwise pass — a target failure is
    a hard failure for the case.
    """

    case_index: int
    input: Mapping[str, Any]
    expected: Mapping[str, Any]
    output: EvalOutput | None
    metric_scores: Mapping[str, float]
    error: str | None
    passed: bool


@dataclass(slots=True, frozen=True)
class EvalMetricResult:
    """One ``@Metric`` aggregated across every case.

    ``aggregator`` is the metric's configured aggregator name (one of
    the six listed in :mod:`ajolopy.eval.aggregators`). ``values``
    preserves the per-case raw scores in dataset order so future
    tooling (AJ-27 ``--compare-with``) can drill into individual cases.

    ``passed`` is ``aggregate >= pass_threshold`` for every aggregator
    family, including ``count_passing`` (whose aggregate is itself the
    fraction of cases passing — for example, ``pass_threshold=0.8``
    means "at least 80% of cases passed individually").
    """

    name: str
    aggregator: str
    weight: float
    pass_threshold: float
    values: tuple[float, ...]
    aggregate: float
    passed: bool


@dataclass(slots=True, frozen=True)
class EvalRun:
    """The full snapshot of one :meth:`EvalRunner.run` execution.

    Returned in memory from every run; opt-in persistence is provided
    by :meth:`save` (defined in :mod:`ajolopy.eval.storage` and bound
    onto the class at import time).

    ``dataset_sha256`` is the hex sha256 of the dataset file contents
    when the dataset exposes a ``path`` attribute (the v0.1 default,
    :class:`~ajolopy.eval.jsonl.JSONLDataset`). Custom in-memory
    datasets without a backing file produce ``None``; this is fine for
    the in-memory ``EvalRun`` and only matters when persisting via
    :meth:`save` / comparing via
    :func:`~ajolopy.eval.comparison.compare_runs`.
    """

    suite: str
    timestamp: str
    target_kind: Literal["agent", "workflow"]
    target_name: str
    dataset_path: str | None
    dataset_sha256: str | None
    threshold: float
    concurrency: int
    metrics: Mapping[str, EvalMetricResult]
    cases: tuple[EvalCaseResult, ...]
    aggregate_score: float
    passed: bool

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        """Persist this run to a JSON snapshot; return the written path.

        Default location is ``.ajolopy/eval-runs/<timestamp>.json``.
        Dispatches through :data:`_SAVE_EVAL_RUN`, which the package
        ``__init__`` binds to
        :func:`ajolopy.eval.storage.save_eval_run`. The indirection
        keeps this module import-free of :mod:`ajolopy.eval.storage`
        (avoids a CodeQL-flagged cyclic import).
        """
        if _save_eval_run is None:
            raise RuntimeError(
                "EvalRun.save dispatcher is not bound. Import "
                "ajolopy.eval (which wires the persistence layer) before "
                "calling EvalRun.save."
            )
        return _save_eval_run(self, path)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> EvalRun:
        """Read a previously-written :class:`EvalRun` JSON snapshot.

        Dispatches through :data:`_LOAD_EVAL_RUN`. See :meth:`save`
        for the rationale behind the indirection.
        Raises :class:`EvalRunError` on a schema-version mismatch.
        """
        _ = cls
        if _load_eval_run is None:
            raise RuntimeError(
                "EvalRun.load dispatcher is not bound. Import "
                "ajolopy.eval (which wires the persistence layer) before "
                "calling EvalRun.load."
            )
        return _load_eval_run(path)


@dataclass(slots=True, frozen=True)
class MetricDelta:
    """One metric's prev/curr aggregate delta from
    :func:`~ajolopy.eval.comparison.compare_runs`.

    ``is_regression`` is ``curr_aggregate < prev_aggregate - 1e-3``;
    the floor absorbs float noise from the aggregation pipeline. New
    metrics (present only in ``curr``) carry ``prev_aggregate=NaN``
    and are NEVER classified as regressions.
    """

    name: str
    prev_aggregate: float
    curr_aggregate: float
    delta: float
    is_regression: bool


@dataclass(slots=True, frozen=True)
class EvalComparison:
    """Output of :func:`~ajolopy.eval.comparison.compare_runs`.

    The two case-index tuples are ordered ascending so consumers can
    iterate stably; for an unchanged suite both tuples are empty.
    """

    suite: str
    prev_timestamp: str
    curr_timestamp: str
    metric_deltas: Mapping[str, MetricDelta]
    newly_failing_case_indices: tuple[int, ...]
    newly_passing_case_indices: tuple[int, ...]
