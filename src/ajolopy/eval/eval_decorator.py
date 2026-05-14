"""``@Eval`` class decorator + decoration-time validation.

Named with the ``_decorator`` suffix because ``eval`` is a Python
builtin and shadowing it inside the package would break ``Eval.eval``
references and confuse static analysers. The module exports the
:func:`Eval` symbol unchanged; the package ``__init__`` re-exports it.

The decorator is inert at decoration time apart from validation:

1. Validate kwargs (exactly-one-of ``agent=`` / ``workflow=``,
   ``threshold`` and ``concurrency`` in range, ``dataset`` coercible
   via :func:`resolve_dataset`).
2. Walk the class for ``@Metric`` markers via
   :func:`discover_metrics`. Refuse a metric-less suite.
3. Stamp :class:`EvalMetadata` on the class as ``_ajolopy_eval``.

No dataset open, no agent invocation, no span emission happens here —
that all moves to :class:`~ajolopy.eval.runner.EvalRunner.run`. The
class returns ``type[T]`` unchanged so pyright sees the original
public surface (the ``@Eval`` decorator never mutates class methods).

CodeQL note: ``@Eval`` runs substantial pre-``_decorate`` validation
that may raise. Per the CLAUDE.md guidance we use a manual ``TypeVar``
(not PEP 695 ``def Eval[T]``) to avoid the "Potentially uninitialized
local variable" false positive that bit ``@MCP``.
"""

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from .errors import DatasetError, EvalConfigError
from .metric import discover_metrics
from .resolver import resolve_dataset

if TYPE_CHECKING:
    import os
    from collections.abc import Callable, Mapping

    from .dataset import Dataset
    from .metric import MetricMetadata


__all__ = [
    "EVAL_MARKER",
    "Eval",
    "EvalMetadata",
]


# Public attribute name used by the runner to find the resolved
# metadata. Lives on the class itself (not on a base class) so the
# runner can detect "this is an @Eval suite" with a single ``hasattr``.
EVAL_MARKER = "_ajolopy_eval"

# Defaults — kept module-level so tests, docs, and other primitives can
# reference the same constants if they ever need to assert defaults.
_DEFAULT_THRESHOLD = 0.5
_DEFAULT_CONCURRENCY = 5

# Manual ``TypeVar`` (NOT PEP 695 ``def Eval[T]``): the decorator body
# performs pre-``_decorate`` validation that may raise. PEP 695
# ``def Eval[T]`` would trip CodeQL's "Potentially uninitialized local
# variable" check on the type parameter when the surrounding code raises.
# The CLAUDE.md "CodeQL false-positive precedents" entry documents this.
T = TypeVar("T")

_TargetKind = Literal["agent", "workflow"]


@dataclass(slots=True, frozen=True)
class EvalMetadata:
    """Resolved per-suite configuration attached at decoration time.

    The runner reads every field on each :meth:`run`; freezing the
    dataclass prevents accidental edits to a class-level field while a
    run is in flight (especially important for the case ordering
    guarantee when cases run concurrently).

    ``target_cls`` is the ``@Agent``-decorated or ``@Workflow``-decorated
    class, not an instance — the runner instantiates it per case (for
    workflow targets, the workflow runtime owns its own state).
    ``dataset_spec`` is the raw form passed to ``@Eval(dataset=...)``;
    :func:`resolve_dataset` runs once at the start of each run, so a
    file-backed dataset is re-read on every call (this keeps the
    decoration-time cost low when the suite is imported but never
    executed).
    """

    suite_cls: type[Any]
    target_cls: type[Any]
    target_kind: _TargetKind
    dataset_spec: str | os.PathLike[str] | Dataset | type[Dataset]
    threshold: float
    concurrency: int
    metrics: Mapping[str, MetricMetadata]


def Eval(  # noqa: N802 — public surface mirrors the Brief's primitive name.
    *,
    agent: type[Any] | None = None,
    workflow: type[Any] | None = None,
    dataset: str | os.PathLike[str] | Dataset | type[Dataset],
    threshold: float = _DEFAULT_THRESHOLD,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> Callable[[type[T]], type[T]]:
    """Class decorator factory — see ``specs/eval.md`` for the full surface.

    Returns a decorator that stamps :class:`EvalMetadata` onto the
    class as ``_ajolopy_eval``. The class type is preserved so pyright
    keeps seeing the original public surface; the runner uses the
    metadata at call time without touching the class methods.
    """
    target_cls, target_kind = _validate_target(agent=agent, workflow=workflow)
    _validate_threshold(threshold)
    _validate_concurrency(concurrency)
    _validate_dataset_spec(dataset)

    def _decorate(cls: type[T]) -> type[T]:
        metrics = discover_metrics(cls)
        if not metrics:
            raise EvalConfigError(
                f"@Eval class {cls.__name__!r} has no @Metric methods; an "
                f"Eval suite needs at least one @Metric method to produce a "
                f"score."
            )
        metadata = EvalMetadata(
            suite_cls=cls,
            target_cls=target_cls,
            target_kind=target_kind,
            dataset_spec=dataset,
            threshold=threshold,
            concurrency=concurrency,
            metrics=metrics,
        )
        cls._ajolopy_eval = metadata  # type: ignore[attr-defined]
        return cls

    return _decorate


# ---------------------------------------------------------------------------
# Decoration-time validators
# ---------------------------------------------------------------------------


def _validate_target(
    *,
    agent: type[Any] | None,
    workflow: type[Any] | None,
) -> tuple[type[Any], _TargetKind]:
    """Validate the ``agent=`` / ``workflow=`` mutual-exclusion rule.

    Exactly one of the two MUST be set; either neither or both raises
    :class:`EvalConfigError`. The chosen class must be decorated with
    its matching primitive (``@Agent`` / ``@Workflow``); we detect that
    by reading the per-decorator marker (``_agent_runtime`` /
    ``_workflow_runtime``) so this module stays free of the agent /
    workflow imports (avoiding the cycle ``eval → agent → ... → eval``).
    """
    if agent is not None and workflow is not None:
        raise EvalConfigError(
            "@Eval requires exactly one of agent= / workflow=; both were "
            f"provided ({agent.__name__!r} and {workflow.__name__!r})."
        )
    if agent is None and workflow is None:
        raise EvalConfigError(
            "@Eval requires either agent=<AgentClass> or workflow=<WorkflowClass>; "
            "neither was provided."
        )
    if agent is not None:
        if not _has_marker(agent, "_agent_runtime"):
            raise EvalConfigError(
                f"@Eval(agent={agent.__name__!r}) must be decorated with "
                f"@Agent; the class has no _agent_runtime attribute."
            )
        return agent, "agent"
    # workflow is not None by the elimination above.
    assert workflow is not None  # noqa: S101 — pyright narrowing without runtime cost.
    if not _has_marker(workflow, "_workflow_runtime"):
        raise EvalConfigError(
            f"@Eval(workflow={workflow.__name__!r}) must be decorated with "
            f"@Workflow; the class has no _workflow_runtime attribute."
        )
    return workflow, "workflow"


def _has_marker(cls: type[Any], attr: str) -> bool:
    """``True`` when ``cls`` carries the requested decorator marker.

    Reads the attribute via :func:`getattr` so subclasses inherit the
    marker correctly (an ``@Agent`` class subclassed by the user still
    counts as an agent target — the user's responsibility to ensure
    the subclass's ``run`` method works with ``**case.input``).
    """
    if not inspect.isclass(cls):
        return False
    return getattr(cls, attr, None) is not None


def _validate_threshold(threshold: float) -> None:
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise EvalConfigError(
            f"@Eval threshold must be a number in [0.0, 1.0], got "
            f"{threshold!r} of type {type(threshold).__name__}."
        )
    if not 0.0 <= threshold <= 1.0:
        raise EvalConfigError(f"@Eval threshold must be in [0.0, 1.0], got {threshold}.")


def _validate_concurrency(concurrency: int) -> None:
    if not isinstance(concurrency, int) or isinstance(concurrency, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise EvalConfigError(
            f"@Eval concurrency must be an int >= 1, got {concurrency!r} "
            f"of type {type(concurrency).__name__}."
        )
    if concurrency < 1:
        raise EvalConfigError(f"@Eval concurrency must be >= 1, got {concurrency}.")


def _validate_dataset_spec(spec: object) -> None:
    """Eagerly coerce the spec via :func:`resolve_dataset` and discard.

    Raising at decoration time keeps misconfigured suites from
    surviving import — without this, the user only sees a
    :class:`DatasetError` when they finally call :meth:`run`. The
    coerced :class:`Dataset` is intentionally NOT cached: the run
    re-resolves on every invocation so live edits to the dataset file
    take effect without rebooting the process.
    """
    try:
        resolve_dataset(spec)  # type: ignore[arg-type]
    except DatasetError:
        # Bubble the dataset-layer error verbatim per the spec — its
        # diagnostics (line numbers, "dataset is empty", etc.) are more
        # actionable than a wrapped ``EvalConfigError``. The caller can
        # still catch ``DatasetError`` from the import-time stack.
        raise
