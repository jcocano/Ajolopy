"""Errors raised by the ``ajolopy.eval`` package.

The dataset layer (AJ-25) groups its failures under
:class:`DatasetError`; the ``@Eval`` / ``@Metric`` layer (AJ-4) layers
its own error families on top:

- :class:`EvalConfigError` — decoration-time misconfiguration of an
  ``@Eval`` class (missing target, both ``agent=`` and ``workflow=``
  set, bad thresholds, zero ``@Metric`` methods, duplicate metric
  names, ...).
- :class:`MetricConfigError` — decoration-time misconfiguration of a
  ``@Metric`` method (bad ``aggregator=``, weight outside the legal
  range, signature mismatch, ...).
- :class:`EvalRunError` — runtime failures during ``EvalRunner.run()``
  (empty dataset, schema-version mismatch on load, ...).
- :class:`MetricRuntimeError` — a ``@Metric`` method returned a
  non-numeric value or raised; the runner captures this per case and
  marks the case failed without aborting the suite.
- :class:`EvalComparisonError` — :func:`compare_runs` rejected the
  pair (suite mismatch, dataset sha256 mismatch, case count
  mismatch, ...).

All five live alongside :class:`DatasetError` so callers can write a
single ``except (DatasetError, EvalConfigError, ...)`` clause. They do
NOT share a common base — the dataset and eval layers fail for
unrelated reasons and conflating them would obscure user diagnostics.
"""


class DatasetError(Exception):
    """Base class for any error raised by the dataset layer."""


class DatasetFileError(DatasetError):
    """The dataset file is missing, not a file, or unreadable."""


class DatasetSchemaError(DatasetError):
    """The dataset contents do not match the ``{input, expected}`` contract.

    ``line`` is the 1-based file line where the problem was detected, or
    ``None`` for whole-file errors (empty dataset).
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line: int | None = line


class EvalConfigError(Exception):
    """The ``@Eval`` class is misconfigured at decoration time."""


class MetricConfigError(Exception):
    """The ``@Metric`` decorator received invalid kwargs or a bad signature."""


class EvalRunError(Exception):
    """A runtime failure occurred while executing an ``EvalRunner.run()``.

    Distinct from :class:`MetricRuntimeError` so callers can drop the
    suite on hard failures (empty dataset, schema mismatch on load)
    without confusing it with per-case metric noise.
    """


class MetricRuntimeError(Exception):
    """A ``@Metric`` method raised or returned a non-numeric value.

    Captured per case by the runner so the suite continues running. The
    exception text is bubbled into :class:`~ajolopy.eval.EvalCaseResult`
    via its ``error`` field.
    """


class EvalComparisonError(Exception):
    """:func:`compare_runs` refused the pair as not comparable.

    Raised on suite-name mismatch, dataset sha256 mismatch (different
    dataset), or case-count mismatch. AJ-27's CLI surfaces a ``--force``
    flag later for the dataset-changed case.
    """


__all__ = [
    "DatasetError",
    "DatasetFileError",
    "DatasetSchemaError",
    "EvalComparisonError",
    "EvalConfigError",
    "EvalRunError",
    "MetricConfigError",
    "MetricRuntimeError",
]
