"""Public surface of the ``ajolopy.eval`` package.

Two layers compose this package:

- **Dataset layer (AJ-25)** — :class:`Case`, :class:`Dataset`,
  :class:`JSONLDataset`, :func:`resolve_dataset`, and the
  :class:`DatasetError` hierarchy. Stable since AJ-25.
- **Eval / Metric layer (AJ-4)** — :func:`Eval` and :func:`Metric`
  decorators, :class:`EvalRunner`, the
  :class:`EvalRun` / :class:`EvalCaseResult` / :class:`EvalMetricResult`
  / :class:`EvalOutput` result tree, the :class:`MetricDelta` /
  :class:`EvalComparison` comparison tree, :func:`compare_runs`, and
  the :class:`EvalConfigError` / :class:`MetricConfigError` /
  :class:`EvalRunError` / :class:`MetricRuntimeError` /
  :class:`EvalComparisonError` errors.

Top-level re-exports under :mod:`ajolopy` are limited to the two
primitive decorators (``Eval`` and ``Metric``) — every other symbol
stays under :mod:`ajolopy.eval` to keep the top-level surface tight.

Importing this module is intentionally cheap: only the dataclass
shapes, decorator factories, and runner class are materialised. The
runner does not open the dataset or touch the network until its
:meth:`run` method is called.
"""

from .aggregators import AGGREGATOR_NAMES
from .case import Case
from .comparison import compare_runs
from .dataset import Dataset
from .errors import (
    DatasetError,
    DatasetFileError,
    DatasetSchemaError,
    EvalComparisonError,
    EvalConfigError,
    EvalRunError,
    MetricConfigError,
    MetricRuntimeError,
)
from .eval_decorator import Eval, EvalMetadata
from .jsonl import JSONLDataset
from .metric import Metric, MetricMetadata, discover_metrics
from .resolver import resolve_dataset
from .results import (
    EvalCaseResult,
    EvalComparison,
    EvalMetricResult,
    EvalOutput,
    EvalRun,
    MetricDelta,
)
from .runner import EvalRunner
from .storage import EVAL_RUN_SCHEMA_VERSION

__all__ = [
    "AGGREGATOR_NAMES",
    "EVAL_RUN_SCHEMA_VERSION",
    "Case",
    "Dataset",
    "DatasetError",
    "DatasetFileError",
    "DatasetSchemaError",
    "Eval",
    "EvalCaseResult",
    "EvalComparison",
    "EvalComparisonError",
    "EvalConfigError",
    "EvalMetadata",
    "EvalMetricResult",
    "EvalOutput",
    "EvalRun",
    "EvalRunError",
    "EvalRunner",
    "JSONLDataset",
    "Metric",
    "MetricConfigError",
    "MetricDelta",
    "MetricMetadata",
    "MetricRuntimeError",
    "compare_runs",
    "discover_metrics",
    "resolve_dataset",
]
