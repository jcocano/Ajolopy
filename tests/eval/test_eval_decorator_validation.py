"""Decoration-time validation tests for ``@Eval``.

The decorator's promise is "if it imports clean, the run will not
explode for a configuration reason". Every misconfiguration that the
spec calls out has a test here so future refactors keep the gate in
place.
"""

from pathlib import Path

import pytest

from ajolopy import Agent, Eval, Metric, Workflow
from ajolopy.eval import EvalConfigError
from ajolopy.eval.errors import DatasetFileError
from ajolopy.providers import register_provider
from tests.agent.conftest import FakeProvider

FIXTURES = Path(__file__).parent / "fixtures"


def _make_agent(name: str = "Support") -> type:
    register_provider("anthropic", FakeProvider, overwrite=True)

    @Agent(model="claude-opus-4-7", system="you are helpful")
    class _Agent:
        pass

    _Agent.__name__ = name
    return _Agent


def _make_workflow() -> type:
    register_provider("anthropic", FakeProvider, overwrite=True)
    agent = _make_agent("Specialist")

    @Workflow(agents=[agent], coordinator="claude-opus-4-7")
    class Team:
        pass

    return Team


def test_eval_with_agent_stamps_metadata() -> None:
    support = _make_agent()

    @Eval(agent=support, dataset=str(FIXTURES / "support.jsonl"))
    class SupportEval:
        @Metric
        def helpful(self, output, expected) -> float:
            return 1.0

    metadata = SupportEval._ajolopy_eval  # type: ignore[attr-defined]
    assert metadata.target_kind == "agent"
    assert metadata.target_cls is support
    assert metadata.threshold == 0.5
    assert metadata.concurrency == 5
    assert "helpful" in metadata.metrics


def test_eval_with_workflow_stamps_metadata() -> None:
    workflow_cls = _make_workflow()

    @Eval(workflow=workflow_cls, dataset=str(FIXTURES / "support.jsonl"))
    class TeamEval:
        @Metric
        def ok(self, output, expected) -> float:
            return 1.0

    metadata = TeamEval._ajolopy_eval  # type: ignore[attr-defined]
    assert metadata.target_kind == "workflow"
    assert metadata.target_cls is workflow_cls


def test_eval_with_both_agent_and_workflow_raises() -> None:
    support = _make_agent()
    workflow_cls = _make_workflow()
    with pytest.raises(EvalConfigError, match="exactly one"):

        @Eval(agent=support, workflow=workflow_cls, dataset=str(FIXTURES / "support.jsonl"))
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


def test_eval_with_neither_target_raises() -> None:
    with pytest.raises(EvalConfigError, match="neither was provided"):

        @Eval(dataset=str(FIXTURES / "support.jsonl"))
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


def test_eval_with_plain_class_as_agent_raises() -> None:
    class Plain:
        pass

    with pytest.raises(EvalConfigError, match="@Agent"):

        @Eval(agent=Plain, dataset=str(FIXTURES / "support.jsonl"))
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


def test_eval_with_plain_class_as_workflow_raises() -> None:
    class Plain:
        pass

    with pytest.raises(EvalConfigError, match="@Workflow"):

        @Eval(workflow=Plain, dataset=str(FIXTURES / "support.jsonl"))
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


def test_eval_without_metrics_raises() -> None:
    support = _make_agent()
    with pytest.raises(EvalConfigError, match="at least one @Metric"):

        @Eval(agent=support, dataset=str(FIXTURES / "support.jsonl"))
        class _NoMetrics:
            pass


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1, -0.001])
def test_eval_threshold_out_of_range_raises(bad_threshold: float) -> None:
    support = _make_agent()
    with pytest.raises(EvalConfigError, match=r"threshold"):

        @Eval(agent=support, dataset=str(FIXTURES / "support.jsonl"), threshold=bad_threshold)
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


@pytest.mark.parametrize("bad_concurrency", [0, -1])
def test_eval_concurrency_out_of_range_raises(bad_concurrency: int) -> None:
    support = _make_agent()
    with pytest.raises(EvalConfigError, match=r"concurrency"):

        @Eval(
            agent=support,
            dataset=str(FIXTURES / "support.jsonl"),
            concurrency=bad_concurrency,
        )
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


def test_eval_propagates_dataset_error(tmp_path: Path) -> None:
    """A bad ``dataset=`` form surfaces as ``DatasetError``, not ``EvalConfigError``."""
    support = _make_agent()
    with pytest.raises(DatasetFileError):

        @Eval(agent=support, dataset=str(tmp_path / "does_not_exist.jsonl"))
        class _Bad:
            @Metric
            def m(self, output, expected) -> float:
                return 1.0


def test_duplicate_metric_name_raises() -> None:
    """Two ``@Metric`` methods sharing a stored name are rejected.

    The framework stores the metric's name on the
    :class:`MetricMetadata` at decoration time. ``discover_metrics``
    walks ``__dict__`` in insertion order; two markers carrying the
    same stored name surface as :class:`EvalConfigError`.
    """
    from ajolopy.eval.metric import (
        METRIC_MARKER,
        MetricMetadata,
        discover_metrics,
    )
    from ajolopy.eval.metric import (
        Metric as _Metric,
    )

    def m_a(self, output, expected) -> float:
        return 1.0

    def m_b(self, output, expected) -> float:
        return 0.0

    _Metric(m_a)
    _Metric(m_b)
    # Replace the second marker with one that reuses the first
    # marker's name — that mimics two metrics colliding on the same
    # logical identifier.
    original_b: MetricMetadata = getattr(m_b, METRIC_MARKER)
    m_b._ajolopy_metric = MetricMetadata(  # type: ignore[attr-defined]
        name="m_a",
        fn=original_b.fn,
        aggregator=original_b.aggregator,
        weight=original_b.weight,
        pass_threshold=original_b.pass_threshold,
        is_async=original_b.is_async,
    )
    namespace: dict[str, object] = {"m_a": m_a, "alias_for_m_a": m_b}
    cls = type("DupSuite", (), namespace)

    with pytest.raises(EvalConfigError, match="duplicate metric"):
        discover_metrics(cls)
