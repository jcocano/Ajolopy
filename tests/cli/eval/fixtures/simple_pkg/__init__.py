"""Package fixture for the discovery tests.

Declares two ``@Eval``-marked classes here and one inside the
``one`` submodule so the discovery walker has both flat and recursive
work to do.
"""

from collections.abc import Mapping
from pathlib import Path

from ajolopy.eval.eval_decorator import EVAL_MARKER, EvalMetadata
from ajolopy.eval.metric import MetricMetadata


def _make_metadata(suite_cls: type, target_cls: type) -> EvalMetadata:
    def _metric_fn(self: object, output: object, expected: Mapping[str, object]) -> float:
        return 1.0

    metrics = {
        "helpful": MetricMetadata(
            name="helpful",
            fn=_metric_fn,
            aggregator="mean",
            weight=1.0,
            pass_threshold=0.5,
            is_async=False,
        )
    }
    fixture_path = Path(__file__).resolve().parents[4] / "eval" / "fixtures" / "support.jsonl"
    return EvalMetadata(
        suite_cls=suite_cls,
        target_cls=target_cls,
        target_kind="agent",
        dataset_spec=str(fixture_path),
        threshold=0.5,
        concurrency=1,
        metrics=metrics,
    )


class _PkgAgent:
    class _Runtime:
        _models: list[tuple[str, object]] = [("claude-opus-4-7", object())]

    _agent_runtime = _Runtime()


class PackageLevelSuiteA:
    """First package-level suite (declaration order: 1st)."""


class PackageLevelSuiteB:
    """Second package-level suite (declaration order: 2nd)."""


setattr(PackageLevelSuiteA, EVAL_MARKER, _make_metadata(PackageLevelSuiteA, _PkgAgent))
setattr(PackageLevelSuiteB, EVAL_MARKER, _make_metadata(PackageLevelSuiteB, _PkgAgent))
