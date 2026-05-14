"""Decoration-time validation for ``@Metric``.

Both forms (bare and parameterised) must work, and every kwarg has a
range it must respect. The signature check fires for methods with
fewer than the required three positional parameters.
"""

import pytest

from ajolopy.eval import Metric, MetricConfigError
from ajolopy.eval.metric import METRIC_MARKER


def test_bare_form_stamps_defaults() -> None:
    @Metric
    def helpful(self, output, expected) -> float:
        return 1.0

    marker = getattr(helpful, METRIC_MARKER, None)
    assert marker is not None
    assert marker.name == "helpful"
    assert marker.aggregator == "mean"
    assert marker.weight == 1.0
    assert marker.pass_threshold == 0.5
    assert marker.is_async is False


def test_parameterised_form_stamps_supplied_values() -> None:
    @Metric(aggregator="p95", weight=0.5, pass_threshold=0.8)
    def latency_ms(self, output, expected) -> float:
        return 1.0

    marker = getattr(latency_ms, METRIC_MARKER, None)
    assert marker is not None
    assert marker.aggregator == "p95"
    assert marker.weight == 0.5
    assert marker.pass_threshold == 0.8


def test_empty_parens_form_works() -> None:
    @Metric()
    def helpful(self, output, expected) -> float:
        return 1.0

    marker = getattr(helpful, METRIC_MARKER, None)
    assert marker is not None
    assert marker.aggregator == "mean"


def test_async_metric_is_flagged() -> None:
    @Metric
    async def llm_judge(self, output, expected) -> float:
        return 1.0

    marker = getattr(llm_judge, METRIC_MARKER, None)
    assert marker is not None
    assert marker.is_async is True


def _stub_metric_body(self, output, expected) -> float:
    """Reusable callable passed to ``Metric(...)`` calls that should fail.

    Defined once so each parametric test can call the decorator with a
    real function (the decorator's signature check accepts it) and the
    raised error comes from the configuration, not the signature.
    """
    return 1.0


def test_unknown_aggregator_raises() -> None:
    with pytest.raises(MetricConfigError, match="unknown aggregator"):
        Metric(aggregator="bogus")(_stub_metric_body)  # type: ignore[arg-type]


def test_error_message_lists_known_aggregators() -> None:
    with pytest.raises(MetricConfigError, match="mean") as info:
        Metric(aggregator="bogus")(_stub_metric_body)  # type: ignore[arg-type]

    msg = str(info.value)
    for name in ("mean", "min", "max", "p50", "p95", "count_passing"):
        assert name in msg


@pytest.mark.parametrize("bad_weight", [0, -1, -0.5])
def test_non_positive_weight_raises(bad_weight: float) -> None:
    with pytest.raises(MetricConfigError, match=r"weight"):
        Metric(weight=bad_weight)(_stub_metric_body)


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1, 2.0])
def test_pass_threshold_out_of_range_raises(bad_threshold: float) -> None:
    with pytest.raises(MetricConfigError, match=r"pass_threshold"):
        Metric(pass_threshold=bad_threshold)(_stub_metric_body)


def test_signature_mismatch_raises() -> None:
    def too_few(self, output) -> float:  # missing expected
        return 1.0

    with pytest.raises(MetricConfigError, match=r"three positional"):
        Metric(too_few)
