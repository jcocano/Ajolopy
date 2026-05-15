"""Shared fixtures + helpers for ``ajolopy eval`` CLI tests.

The CLI tests do NOT exercise the real :class:`EvalRunner` — instead
they:

- build fake suite classes that carry the ``_ajolopy_eval`` marker
  with the right shape (``EvalMetadata`` + per-suite metrics) so the
  command's discovery / filter / threshold-override paths see a real
  class shape, and
- monkeypatch the runner's :meth:`run` method on the CLI module's
  ``EvalRunner`` symbol to return canned :class:`EvalRun` snapshots.

Together these let every test assert against the orchestration logic
(exit codes, JSON shapes, prompts) without spinning a real agent /
LLM provider.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from ajolopy.eval.eval_decorator import EVAL_MARKER, EvalMetadata
from ajolopy.eval.metric import MetricMetadata
from ajolopy.eval.results import (
    EvalCaseResult,
    EvalMetricResult,
    EvalOutput,
    EvalRun,
)

# ---------------------------------------------------------------------------
# Synthetic suite builders
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Stand-in for an ``@Agent``-decorated class.

    The CLI inspects ``target_cls._agent_runtime._models[0][0]`` only
    under ``--dry-run``; this stub satisfies that contract without
    pulling in the real :class:`AgentRuntime`.
    """

    class _Runtime:
        def __init__(self, model: str) -> None:
            self._models: list[tuple[str, object]] = [(model, object())]

    _agent_runtime = _Runtime("claude-sonnet-4-7")


def make_suite_class(
    name: str,
    *,
    model: str = "claude-sonnet-4-7",
    threshold: float = 0.5,
    metric_names: tuple[str, ...] = ("helpful",),
    async_metric: bool = False,
    module: str = "tests.cli.eval.fixtures._fakes",
) -> type[Any]:
    """Build a synthetic ``@Eval``-marked class for CLI tests.

    The class carries a real :class:`EvalMetadata` so the CLI's
    discovery + threshold-override paths see the documented shape.
    The metadata uses a dataset path that points at the existing
    ``support.jsonl`` fixture (3 cases) so dry-run case counts are
    deterministic.
    """

    def _metric_fn(self: object, output: object, expected: Mapping[str, object]) -> float:
        return 1.0

    metrics: dict[str, MetricMetadata] = {}
    for metric_name in metric_names:
        metrics[metric_name] = MetricMetadata(
            name=metric_name,
            fn=_metric_fn,
            aggregator="mean",
            weight=1.0,
            pass_threshold=0.5,
            is_async=async_metric,
        )

    agent_cls = type(
        f"_Agent_{name}",
        (_FakeAgent,),
        {"_agent_runtime": _FakeAgent._Runtime(model)},
    )

    cls: type[Any] = type(name, (), {})
    cls.__module__ = module
    metadata = EvalMetadata(
        suite_cls=cls,
        target_cls=agent_cls,
        target_kind="agent",
        dataset_spec=str(
            Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "support.jsonl"
        ),
        threshold=threshold,
        concurrency=1,
        metrics=metrics,
    )
    setattr(cls, EVAL_MARKER, metadata)
    return cls


def make_eval_run(
    suite: str,
    *,
    timestamp: str = "2026-05-14T22-30-00Z",
    aggregate_score: float = 0.9,
    threshold: float = 0.5,
    passed: bool = True,
    metric_aggregates: Mapping[str, float] | None = None,
    cases: int = 3,
    dataset_sha256: str | None = "feedfeed",
) -> EvalRun:
    """Build a canned :class:`EvalRun` with stable defaults."""
    metric_aggregates = metric_aggregates or {"helpful": aggregate_score}
    metrics: dict[str, EvalMetricResult] = {}
    for name, agg in metric_aggregates.items():
        metrics[name] = EvalMetricResult(
            name=name,
            aggregator="mean",
            weight=1.0,
            pass_threshold=0.5,
            values=tuple(agg for _ in range(cases)),
            aggregate=agg,
            passed=agg >= 0.5,
        )

    case_results: list[EvalCaseResult] = []
    for i in range(cases):
        case_results.append(
            EvalCaseResult(
                case_index=i,
                input={"message": f"q{i}"},
                expected={"intent": "test"},
                output=EvalOutput(
                    text=f"a{i}",
                    latency_ms=1.0,
                    cost_usd=0.0001,
                    trace_id=None,
                    raw=f"a{i}",
                    tool_calls=(),
                ),
                metric_scores=dict.fromkeys(metric_aggregates, 1.0),
                error=None,
                passed=passed,
            )
        )

    return EvalRun(
        suite=suite,
        timestamp=timestamp,
        target_kind="agent",
        target_name=f"_Agent_{suite}",
        dataset_path="/fake/dataset.jsonl",
        dataset_sha256=dataset_sha256,
        threshold=threshold,
        concurrency=1,
        metrics=metrics,
        cases=tuple(case_results),
        aggregate_score=aggregate_score,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# Runner fakes
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Stand-in for :class:`EvalRunner` used by the CLI tests.

    Records the order in which suites were submitted (handy for the
    declaration-order test) and emits a pre-supplied :class:`EvalRun`
    per call. Subscribers register a per-suite override via
    :meth:`set_run`; suites with no override fall back to the
    constructor default.
    """

    def __init__(
        self,
        *,
        default_run_factory: Any | None = None,
        eval_runs_dir: Path | None = None,
    ) -> None:
        self.eval_runs_dir: Path = eval_runs_dir or Path(".ajolopy/eval-runs")
        self.calls: list[type[Any]] = []
        self.observed_thresholds: list[float] = []
        self._overrides: dict[str, EvalRun] = {}
        self._default_factory = default_run_factory

    def set_run(self, suite_name: str, run: EvalRun) -> None:
        self._overrides[suite_name] = run

    async def run(self, suite_cls: type[Any]) -> EvalRun:
        self.calls.append(suite_cls)
        metadata = getattr(suite_cls, EVAL_MARKER)
        self.observed_thresholds.append(metadata.threshold)
        suite_name = suite_cls.__name__
        if suite_name in self._overrides:
            return self._overrides[suite_name]
        if self._default_factory is not None:
            return self._default_factory(suite_name)
        return make_eval_run(suite_name)


@pytest.fixture
def fake_runner_factory() -> Any:
    """Return a constructor that yields a fresh :class:`_FakeRunner`."""
    return _FakeRunner
