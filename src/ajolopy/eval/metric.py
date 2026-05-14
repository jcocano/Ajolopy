"""``@Metric`` method decorator + metadata discovery.

A ``@Metric`` is a per-method marker that turns one method of an
``@Eval``-decorated class into a metric. Each metric:

- takes ``(self, output: EvalOutput, expected: Mapping[str, Any])``
  and returns a ``float`` per case (sync or async; async metrics are
  awaited by the runner),
- carries decoration-time config: ``aggregator`` (one of the six in
  :mod:`ajolopy.eval.aggregators`), ``weight`` (used by the weighted
  suite aggregate), and ``pass_threshold`` (per-case pass bar AND the
  metric's own aggregate pass bar).

The decorator supports BOTH the bare form (``@Metric``) and the
parameterised form (``@Metric(...)``), expressed via two overloads:

>>> @Metric
... def helpful(self, output, expected) -> float: ...

>>> @Metric(aggregator="p95", weight=0.5, pass_threshold=0.8)
... def latency_ms(self, output, expected) -> float: ...

Both forms attach a :class:`MetricMetadata` object on the resulting
callable's ``_ajolopy_metric`` attribute. The class-walking helper
:func:`discover_metrics` reads those markers when :func:`Eval` runs.
"""

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, overload

from .aggregators import get_aggregator
from .errors import EvalConfigError, MetricConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "Metric",
    "MetricMetadata",
    "discover_metrics",
]


# ---------------------------------------------------------------------------
# Public attribute name used by the runner / discovery to find @Metric markers
# ---------------------------------------------------------------------------
METRIC_MARKER = "_ajolopy_metric"


_AggregatorName = Literal["mean", "min", "max", "p50", "p95", "count_passing"]


@dataclass(slots=True, frozen=True)
class MetricMetadata:
    """Resolved per-metric configuration attached at decoration time.

    The metadata is class-scoped (not instance-scoped) because the
    decorator runs once per class definition. The runner reads these
    fields on every case; freezing the dataclass prevents accidental
    in-place edits from a sneaky metric body.

    ``fn`` is the original (undecorated) callable — the decorator
    returns the function unchanged; the wrapper just attaches metadata.
    ``is_async`` is precomputed via :func:`inspect.iscoroutinefunction`
    so the runner can branch without re-inspecting per case.
    """

    name: str
    fn: Callable[..., Any]
    aggregator: _AggregatorName
    weight: float
    pass_threshold: float
    is_async: bool


# ---------------------------------------------------------------------------
# @Metric public surface (two overloads + one impl)
# ---------------------------------------------------------------------------


@overload
def Metric(fn: Callable[..., Any], /) -> Callable[..., Any]: ...


@overload
def Metric(
    *,
    aggregator: _AggregatorName = "mean",
    weight: float = 1.0,
    pass_threshold: float = 0.5,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


def Metric(  # noqa: N802 — public surface mirrors the Brief's primitive name.
    fn: Callable[..., Any] | None = None,
    /,
    *,
    aggregator: _AggregatorName = "mean",
    weight: float = 1.0,
    pass_threshold: float = 0.5,
) -> Callable[..., Any] | Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a method on an ``@Eval`` class as a metric.

    See the module docstring for the decorator's two-form surface and
    :class:`MetricMetadata` for the resolved metadata shape.
    """
    # Validate kwargs once — they are independent of the wrapped fn.
    _validate_aggregator(aggregator)
    _validate_weight(weight)
    _validate_pass_threshold(pass_threshold)

    def _stamp(target: Callable[..., Any]) -> Callable[..., Any]:
        _validate_signature(target)
        metadata = MetricMetadata(
            name=target.__name__,
            fn=target,
            aggregator=aggregator,
            weight=weight,
            pass_threshold=pass_threshold,
            is_async=inspect.iscoroutinefunction(target),
        )
        # Functions are mutable; attaching an attribute is the
        # idiomatic way to carry framework metadata. Reading it back
        # via ``getattr(fn, METRIC_MARKER, None)`` keeps :func:`discover_metrics`
        # decoupled from the decorator module.
        target._ajolopy_metric = metadata  # type: ignore[attr-defined]
        return target

    # ``@Metric`` bare form: ``Metric`` is called with a function as the
    # first positional arg. ``@Metric()`` parameterised form: ``fn`` is
    # ``None`` and we return ``_stamp`` for the second call.
    if fn is not None:
        return _stamp(fn)
    return _stamp


# ---------------------------------------------------------------------------
# Decoration-time validation helpers
# ---------------------------------------------------------------------------


def _validate_aggregator(aggregator: str) -> None:
    # Reuse the central lookup so the error message is identical to the
    # one the runtime would produce — the user sees one canonical phrasing.
    get_aggregator(aggregator)


def _validate_weight(weight: float) -> None:
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise MetricConfigError(
            f"@Metric weight must be a positive number, got {weight!r} "
            f"of type {type(weight).__name__}."
        )
    if weight <= 0:
        raise MetricConfigError(f"@Metric weight must be > 0, got {weight}.")


def _validate_pass_threshold(pass_threshold: float) -> None:
    if not isinstance(pass_threshold, (int, float)) or isinstance(pass_threshold, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise MetricConfigError(
            f"@Metric pass_threshold must be a number in [0.0, 1.0], got "
            f"{pass_threshold!r} of type {type(pass_threshold).__name__}."
        )
    if not 0.0 <= pass_threshold <= 1.0:
        raise MetricConfigError(
            f"@Metric pass_threshold must be in [0.0, 1.0], got {pass_threshold}."
        )


def _validate_signature(fn: Callable[..., Any]) -> None:
    """Validate that the decorated callable looks like a metric method.

    The metric contract is ``(self, output, expected) -> float``. We
    accept at decoration time anything callable with at least three
    positional parameters (counting ``self``). Extra parameters with
    defaults are tolerated; the runner only ever passes the three
    positional args. Anything with fewer parameters raises a
    :class:`MetricConfigError` with a hint pointing at the documented
    shape so the user does not have to read the spec to find the bug.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise MetricConfigError(
            f"@Metric could not introspect {getattr(fn, '__name__', fn)!r}'s "
            f"signature: {exc}. Metrics must be plain methods of the form "
            f"``def name(self, output, expected) -> float``."
        ) from exc

    positional: list[inspect.Parameter] = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) < 3:
        raise MetricConfigError(
            f"@Metric {getattr(fn, '__name__', fn)!r} must accept at least "
            f"three positional parameters (self, output, expected); got "
            f"{len(positional)}. Documented shape: "
            f"``def {getattr(fn, '__name__', 'metric')}(self, output, expected) -> float``."
        )


# ---------------------------------------------------------------------------
# Discovery — walk a class for @Metric-decorated methods
# ---------------------------------------------------------------------------


def discover_metrics(cls: type[Any]) -> dict[str, MetricMetadata]:
    """Return ``{name: MetricMetadata}`` for every ``@Metric`` on ``cls``.

    Order is class declaration order — Python preserves insertion order
    in ``cls.__dict__`` since 3.7. Reuses (no inheritance walking): only
    attributes defined directly on ``cls`` are considered. ``@Metric``
    methods inherited from a base class are intentionally ignored so a
    base-class metric doesn't leak silently into a sub-suite (composing
    suites is a v0.2 concern; for v0.1 the rule is "one metric per
    suite class definition").

    Raises :class:`EvalConfigError` on duplicate metric names within
    the same class — Python's class-body collator silently overwrites
    duplicate ``def`` lines and the user would otherwise lose metrics
    without warning.
    """
    discovered: dict[str, MetricMetadata] = {}
    for attr_name, attr_value in cls.__dict__.items():
        marker = getattr(attr_value, METRIC_MARKER, None)
        if not isinstance(marker, MetricMetadata):
            continue
        if marker.name in discovered:
            raise EvalConfigError(
                f"duplicate metric name {marker.name!r} on @Eval class "
                f"{cls.__name__!r}; each metric method must have a "
                f"unique name."
            )
        # ``attr_name`` always matches ``marker.name`` for normally-
        # defined methods. We index by the metadata's stored name so
        # the dict ordering is stable even when subclasses rename
        # methods at class-creation time.
        discovered[marker.name] = marker
        # Silence the unused-loop-variable lint without pulling the
        # attribute key out of the metadata path.
        _ = attr_name
    return discovered
