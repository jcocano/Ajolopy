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

# Import :mod:`storage` for its side effect of binding ``save`` /
# ``load`` onto :class:`EvalRun`. Done at the bottom so the binding
# runs after :mod:`results` has defined the class. We explicitly read
# one of the storage helpers below to keep pyright from flagging the
# import as unused — the read is no-cost.
from . import storage
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

# ``storage.EVAL_RUN_SCHEMA_VERSION`` is re-exported below; assigning it
# here is the load-bearing read that keeps the side-effect import alive
# in front of pyright's reachability analysis.
EVAL_RUN_SCHEMA_VERSION = storage.EVAL_RUN_SCHEMA_VERSION

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
