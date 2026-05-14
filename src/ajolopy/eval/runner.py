"""``EvalRunner`` — the concurrent execution engine behind ``@Eval``.

The runner reads the :class:`~ajolopy.eval.eval_decorator.EvalMetadata`
that ``@Eval`` stamped onto the suite class, walks the dataset, and
returns one :class:`~ajolopy.eval.results.EvalRun`.

Concurrency model:

- Cases are dispatched concurrently under an
  :class:`asyncio.Semaphore` sized by ``EvalMetadata.concurrency``.
- :func:`asyncio.gather` collects results. ``return_exceptions=False`` —
  each case runs inside its own ``try/except``, so the gather itself
  never sees a raise from a case worker; the failure is captured as
  :class:`~ajolopy.eval.results.EvalCaseResult.error`.
- Result ordering is independent of execution order. Workers tag every
  result with its 0-based ``case_index`` so the final tuple is sorted
  by index, giving deterministic ``EvalRun.cases``.

Observability:

- One ``eval.run {SuiteName}`` span per :meth:`run` call.
- One ``eval.case {i}`` span per case as a child. The span context is
  carried into each worker via :class:`contextvars` (Python's asyncio
  propagates contextvars across ``gather``); we additionally call
  :meth:`trace.use_span` inside each worker so the case span lives
  under the run span even when the worker awaits before the first
  span open.
- Per-metric per-case scores land on the case span as
  ``ajolopy.eval.score.<metric>`` attributes.
- The ``ajolopy.cost_usd.total`` rollup on the run span sums the
  per-case ``cost_usd`` values via :func:`set_root_cost_total`.

Cost capture:

- For agent targets we call ``target._agent_runtime.run(instance,
  **case.input, cost_sink=per_case_costs)`` so every chat-span cost
  lands in the per-case accumulator. The case's ``cost_usd`` is the
  sum of those entries (``None`` when every entry is ``None``).
- For workflow targets we call the decorator-injected
  ``instance.run(**case.input)`` and set ``cost_usd=None``. The
  workflow's own root span still carries its own cost rollup; the
  eval run does not roll it up further in v0.1 (deeper workflow-side
  cost wiring is left for AJ-31).
"""

import asyncio
import hashlib
import inspect
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import trace as otel_trace

from ajolopy.observability import (
    AJOLOPY_EVAL_AGGREGATE_SCORE,
    AJOLOPY_EVAL_CASE_ERROR,
    AJOLOPY_EVAL_CASE_INDEX,
    AJOLOPY_EVAL_CASE_PASSED,
    AJOLOPY_EVAL_CONCURRENCY,
    AJOLOPY_EVAL_PASSED,
    AJOLOPY_EVAL_SCORE_PREFIX,
    AJOLOPY_EVAL_SUITE,
    AJOLOPY_EVAL_TARGET_KIND,
    AJOLOPY_EVAL_TARGET_NAME,
    AJOLOPY_EVAL_THRESHOLD,
    eval_case_span_name,
    eval_run_span_name,
    get_tracer,
)
from ajolopy.observability.pricing_emit import set_root_cost_total

from .aggregators import get_aggregator
from .errors import EvalRunError, MetricRuntimeError
from .eval_decorator import EVAL_MARKER
from .resolver import resolve_dataset
from .results import EvalCaseResult, EvalMetricResult, EvalOutput, EvalRun

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from opentelemetry.trace import Span

    from .case import Case
    from .dataset import Dataset
    from .eval_decorator import EvalMetadata
    from .metric import MetricMetadata


__all__ = ["EvalRunner"]


_TRACER = get_tracer("ajolopy.eval")


# Default storage location: ``.ajolopy/eval-runs/`` relative to
# :func:`os.getcwd`. The directory is created on first ``save()`` so
# importing the package never touches the filesystem.
DEFAULT_EVAL_RUNS_DIR = Path(".ajolopy") / "eval-runs"


class EvalRunner:
    """Programmatic API for executing an ``@Eval`` suite.

    Sub-class to override :meth:`_invoke_target` (custom invocation —
    e.g. pre-warmed agents) or :meth:`_aggregate_metrics` (custom score
    combinators). See ``specs/eval.md`` §Escape hatches for the
    documented extension points.
    """

    def __init__(self, *, eval_runs_dir: Path | None = None) -> None:
        # Default resolves against cwd lazily on the first save(); the
        # constructor only normalises the path so subclasses can replace it.
        self._eval_runs_dir: Path = (
            eval_runs_dir if eval_runs_dir is not None else DEFAULT_EVAL_RUNS_DIR
        )

    @property
    def eval_runs_dir(self) -> Path:
        """Directory the default save path resolves into."""
        return self._eval_runs_dir

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def run(self, suite_cls: type[Any]) -> EvalRun:
        """Execute the suite end-to-end and return one :class:`EvalRun`.

        Raises :class:`EvalRunError` for whole-run failures (empty
        dataset, missing metadata). Per-case errors are captured into
        :class:`~ajolopy.eval.results.EvalCaseResult.error` and do NOT
        abort the run; the spec calls for a usable :class:`EvalRun`
        even when individual cases fail.
        """
        metadata = self._load_metadata(suite_cls)
        dataset = resolve_dataset(metadata.dataset_spec)
        cases = self._materialise_cases(dataset)
        if not cases:
            raise EvalRunError("dataset has no cases")

        dataset_path, dataset_sha256 = self._compute_dataset_identity(dataset)
        suite_instance = suite_cls()
        suite_name = suite_cls.__name__

        with self._run_span(
            suite_name=suite_name,
            metadata=metadata,
        ) as run_span:
            case_results = await self._execute_cases(
                metadata=metadata,
                suite_instance=suite_instance,
                cases=cases,
                run_span=run_span,
            )
            metric_results = self._aggregate_metrics(metadata=metadata, case_results=case_results)
            aggregate_score = self._compute_weighted_aggregate(metric_results.values())
            passed = aggregate_score >= metadata.threshold

            run_span.set_attribute(AJOLOPY_EVAL_AGGREGATE_SCORE, aggregate_score)
            run_span.set_attribute(AJOLOPY_EVAL_PASSED, passed)
            per_case_costs = [
                case.output.cost_usd if case.output is not None else None for case in case_results
            ]
            set_root_cost_total(run_span, per_case_costs)

        # Build the in-memory result. Case ordering is by ``case_index``
        # — concurrent workers may finish out of order so we sort here.
        ordered_cases = tuple(sorted(case_results, key=lambda c: c.case_index))
        return EvalRun(
            suite=suite_name,
            timestamp=_iso_timestamp(),
            target_kind=metadata.target_kind,
            target_name=metadata.target_cls.__name__,
            dataset_path=str(dataset_path) if dataset_path is not None else None,
            dataset_sha256=dataset_sha256,
            threshold=metadata.threshold,
            concurrency=metadata.concurrency,
            metrics=metric_results,
            cases=ordered_cases,
            aggregate_score=aggregate_score,
            passed=passed,
        )

    # ------------------------------------------------------------------
    # extension points (subclass to override)
    # ------------------------------------------------------------------

    async def _invoke_target(
        self,
        *,
        metadata: EvalMetadata,
        case: Case,
        cost_sink: list[float | None],
    ) -> tuple[object, float, str | None]:
        """Invoke the target for one case; return ``(raw, latency_ms, trace_id)``.

        Default behaviour:

        - For agent targets, drives the runtime's :meth:`run` directly
          so we can pass ``cost_sink``. The agent's decorator-injected
          ``run(self, message)`` does not forward the kwarg, but the
          underlying ``AgentRuntime.run(instance, message, cost_sink=...)``
          does (AJ-6).
        - For workflow targets, uses the decorator-injected
          ``instance.run(**case.input)`` and leaves ``cost_sink``
          untouched (workflow-side cost rollup is AJ-31's concern).
        """
        target_cls = metadata.target_cls
        instance = target_cls()
        start = time.perf_counter()
        if metadata.target_kind == "agent":
            agent_runtime = target_cls._agent_runtime
            raw = await agent_runtime.run(instance, **case.input, cost_sink=cost_sink)
        else:
            # workflow target — the decorator-injected ``run`` handles
            # the cost rollup on its own span; we don't double-count.
            raw = await instance.run(**case.input)
        latency_ms = (time.perf_counter() - start) * 1000.0
        trace_id = _current_trace_id()
        return raw, latency_ms, trace_id

    def _aggregate_metrics(
        self,
        *,
        metadata: EvalMetadata,
        case_results: list[EvalCaseResult],
    ) -> dict[str, EvalMetricResult]:
        """Collapse per-case scores into one :class:`EvalMetricResult` per metric.

        Iterates metrics in declaration order so the resulting dict
        preserves the user's order — handy for human-readable JSON.
        Returns a plain ``dict`` so it satisfies both the
        :class:`Mapping` annotation on :class:`EvalRun` and the
        positional indexing tests use.
        """
        results: dict[str, EvalMetricResult] = {}
        ordered = sorted(case_results, key=lambda c: c.case_index)
        for metric_name, metric_meta in metadata.metrics.items():
            values = tuple(case.metric_scores.get(metric_name, 0.0) for case in ordered)
            aggregator = get_aggregator(metric_meta.aggregator)
            aggregate = aggregator(values, metric_meta.pass_threshold)
            passed = aggregate >= metric_meta.pass_threshold
            results[metric_name] = EvalMetricResult(
                name=metric_name,
                aggregator=metric_meta.aggregator,
                weight=metric_meta.weight,
                pass_threshold=metric_meta.pass_threshold,
                values=values,
                aggregate=aggregate,
                passed=passed,
            )
        return results

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_metadata(suite_cls: type[Any]) -> EvalMetadata:
        metadata = getattr(suite_cls, EVAL_MARKER, None)
        if metadata is None:
            raise EvalRunError(
                f"{suite_cls.__name__!r} is not an @Eval-decorated class "
                f"(missing _ajolopy_eval marker)."
            )
        # No isinstance check — importing EvalMetadata at runtime here
        # would re-introduce the ``eval_decorator → runner`` half of the
        # cycle. The marker contract is "presence => metadata" so a
        # truthy attribute is sufficient.
        return cast("EvalMetadata", metadata)

    @staticmethod
    def _materialise_cases(dataset: Dataset) -> list[Case]:
        # ``Dataset.__iter__`` is sync (the protocol mandates both
        # protocols). We use the sync iterator here because the cases
        # are typically already in memory (``JSONLDataset`` reads the
        # file eagerly at construction); going through ``__aiter__``
        # would add no benefit and bloat the call site.
        return list(iter(dataset))

    @staticmethod
    def _compute_dataset_identity(dataset: Dataset) -> tuple[Path | None, str | None]:
        """Return ``(path, sha256)`` for a dataset, or ``(None, None)``.

        Only datasets with a ``path`` attribute (the v0.1 default
        :class:`JSONLDataset`) participate. Custom in-memory datasets
        return ``(None, None)`` and are excluded from sha-based
        comparison guards in :func:`compare_runs`.
        """
        path = getattr(dataset, "path", None)
        if not isinstance(path, Path):
            return None, None
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return path, None
        return path, digest

    async def _execute_cases(
        self,
        *,
        metadata: EvalMetadata,
        suite_instance: object,
        cases: list[Case],
        run_span: Span,
    ) -> list[EvalCaseResult]:
        """Dispatch every case under a concurrency-bounded gather."""
        semaphore = asyncio.Semaphore(metadata.concurrency)
        # ``use_span`` is the recommended way to make the run span the
        # current span for code that opens its own spans; we capture
        # ``run_span`` so each worker can re-enter the run-span context
        # before opening its case span. Without this, ``asyncio.gather``
        # workers can race the context-var propagation and end up
        # opening case spans under an unrelated parent.
        coros = [
            self._execute_one_case(
                metadata=metadata,
                suite_instance=suite_instance,
                case=case,
                case_index=index,
                semaphore=semaphore,
                run_span=run_span,
            )
            for index, case in enumerate(cases)
        ]
        return await asyncio.gather(*coros)

    async def _execute_one_case(
        self,
        *,
        metadata: EvalMetadata,
        suite_instance: object,
        case: Case,
        case_index: int,
        semaphore: asyncio.Semaphore,
        run_span: Span,
    ) -> EvalCaseResult:
        async with semaphore:
            with otel_trace.use_span(run_span, end_on_exit=False):
                with self._case_span(case_index=case_index) as case_span:
                    return await self._run_case_body(
                        metadata=metadata,
                        suite_instance=suite_instance,
                        case=case,
                        case_index=case_index,
                        case_span=case_span,
                    )

    async def _run_case_body(
        self,
        *,
        metadata: EvalMetadata,
        suite_instance: object,
        case: Case,
        case_index: int,
        case_span: Span,
    ) -> EvalCaseResult:
        cost_sink: list[float | None] = []
        output: EvalOutput | None = None
        error: str | None = None
        try:
            raw, latency_ms, trace_id = await self._invoke_target(
                metadata=metadata,
                case=case,
                cost_sink=cost_sink,
            )
            output = EvalOutput(
                text=raw if isinstance(raw, str) else str(raw),
                latency_ms=latency_ms,
                cost_usd=_sum_costs(cost_sink),
                trace_id=trace_id,
                raw=raw,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        metric_scores, metric_error = await self._evaluate_metrics(
            metadata=metadata,
            suite_instance=suite_instance,
            output=output,
            case=case,
        )
        # If the target failed, surface that error; if the target was
        # OK but a metric raised, surface the metric error.
        if error is None and metric_error is not None:
            error = metric_error

        per_metric_pass = self._compute_per_metric_pass(metadata=metadata, scores=metric_scores)
        passed = (error is None) and all(per_metric_pass.values())

        # Span attributes — written before returning so the span is
        # complete when the context manager closes.
        case_span.set_attribute(AJOLOPY_EVAL_CASE_INDEX, case_index)
        case_span.set_attribute(AJOLOPY_EVAL_CASE_PASSED, passed)
        if error is not None:
            case_span.set_attribute(AJOLOPY_EVAL_CASE_ERROR, error)
        for metric_name, score in metric_scores.items():
            case_span.set_attribute(f"{AJOLOPY_EVAL_SCORE_PREFIX}{metric_name}", score)

        return EvalCaseResult(
            case_index=case_index,
            input=dict(case.input),
            expected=dict(case.expected),
            output=output,
            metric_scores=metric_scores,
            error=error,
            passed=passed,
        )

    async def _evaluate_metrics(
        self,
        *,
        metadata: EvalMetadata,
        suite_instance: object,
        output: EvalOutput | None,
        case: Case,
    ) -> tuple[Mapping[str, float], str | None]:
        """Run every metric for one case; return scores + collected error string.

        On a missing output (target failed) every metric is short-
        circuited to 0.0 — the spec says "all ``metric_scores=0.0``"
        for a target failure. We still iterate the metrics list so the
        resulting dict has the full keyset (handy for the per-metric
        aggregation later).
        """
        scores: dict[str, float] = {}
        errors: list[str] = []
        for metric_name, metric_meta in metadata.metrics.items():
            if output is None:
                scores[metric_name] = 0.0
                continue
            try:
                scores[metric_name] = await _invoke_metric(
                    metric_meta=metric_meta,
                    suite_instance=suite_instance,
                    output=output,
                    expected=case.expected,
                )
            except Exception as exc:
                scores[metric_name] = 0.0
                errors.append(f"metric {metric_name!r} raised: {type(exc).__name__}: {exc}")
        error = "; ".join(errors) if errors else None
        return scores, error

    @staticmethod
    def _compute_per_metric_pass(
        *,
        metadata: EvalMetadata,
        scores: Mapping[str, float],
    ) -> dict[str, bool]:
        """Per-case, per-metric pass: ``score >= metric.pass_threshold``."""
        return {
            metric_name: scores.get(metric_name, 0.0) >= metric_meta.pass_threshold
            for metric_name, metric_meta in metadata.metrics.items()
        }

    @staticmethod
    def _compute_weighted_aggregate(metrics: Any) -> float:
        """``sum(weight * aggregate) / sum(weight)`` across every metric.

        Decoration-time validation guarantees at least one metric with
        weight > 0; the divisor is safe.
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for metric in metrics:
            assert isinstance(metric, EvalMetricResult)  # noqa: S101 — invariant from caller
            total_weight += metric.weight
            weighted_sum += metric.weight * metric.aggregate
        if total_weight == 0.0:
            # Defensive: every metric had weight 0 — should never
            # happen because @Metric refuses weight <= 0 at decoration
            # time. Return 0 rather than divide-by-zero.
            return 0.0
        return weighted_sum / total_weight

    # ------------------------------------------------------------------
    # span helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _run_span(
        self,
        *,
        suite_name: str,
        metadata: EvalMetadata,
    ) -> Generator[Span]:
        with _TRACER.start_as_current_span(eval_run_span_name(suite_name)) as span:
            span.set_attribute(AJOLOPY_EVAL_SUITE, suite_name)
            span.set_attribute(AJOLOPY_EVAL_TARGET_KIND, metadata.target_kind)
            span.set_attribute(AJOLOPY_EVAL_TARGET_NAME, metadata.target_cls.__name__)
            span.set_attribute(AJOLOPY_EVAL_THRESHOLD, metadata.threshold)
            span.set_attribute(AJOLOPY_EVAL_CONCURRENCY, metadata.concurrency)
            yield span

    @contextmanager
    def _case_span(self, *, case_index: int) -> Generator[Span]:
        with _TRACER.start_as_current_span(eval_case_span_name(case_index)) as span:
            yield span


# ---------------------------------------------------------------------------
# module-level helpers
# ---------------------------------------------------------------------------


async def _invoke_metric(
    *,
    metric_meta: MetricMetadata,
    suite_instance: object,
    output: EvalOutput,
    expected: Mapping[str, Any],
) -> float:
    """Call one metric and coerce the return value to ``float``.

    Async metrics are awaited; sync metrics run inline (the metric body
    is expected to be cheap — heavy LLM-as-judge metrics MUST be async
    so they do not block the event loop). Non-numeric returns raise
    :class:`MetricRuntimeError` so the caller can capture the failure
    into the case's error field without aborting the suite.
    """
    if metric_meta.is_async:
        raw_score = await metric_meta.fn(suite_instance, output, expected)
    else:
        result = metric_meta.fn(suite_instance, output, expected)
        # ``inspect.isawaitable`` covers the case where a sync metric
        # accidentally returns a coroutine (e.g. via partial-application
        # of an async helper). We await it transparently.
        if inspect.isawaitable(result):
            raw_score = await result
        else:
            raw_score = result
    if isinstance(raw_score, bool):
        # bool is a subclass of int; preserve the explicit cast so the
        # downstream ``isinstance(..., (int, float))`` check below still
        # rejects non-numeric returns.
        return float(raw_score)
    if not isinstance(raw_score, (int, float)):
        raise MetricRuntimeError(
            f"metric {metric_meta.name!r} must return a number, got "
            f"{type(raw_score).__name__}: {raw_score!r}."
        )
    return float(raw_score)


def _sum_costs(cost_sink: list[float | None]) -> float | None:
    """Sum a per-case cost accumulator; return ``None`` when all entries are ``None``.

    Mirrors :func:`set_root_cost_total`'s semantics so the case's
    ``cost_usd`` and the run's ``ajolopy.cost_usd.total`` use the same
    rule for absent cost data.
    """
    known = [c for c in cost_sink if c is not None]
    if not known:
        return None
    return float(sum(known))


def _current_trace_id() -> str | None:
    """Return the current OTel span's trace id as 32-char hex, or ``None``."""
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"


def _iso_timestamp() -> str:
    """ISO 8601 UTC timestamp with ``Z`` suffix (no microseconds)."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
