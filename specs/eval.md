# AJ-4 — `@Eval` decorator + `@Metric` + regression-detection core

> Tracked in [`board.json`](../board.json) as `AJ-4`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth: Brief v4.0 §"Killer demo Paso 2" + `09 - Eval framework`
> (anatomy of an eval, metric semantics, dataset format, run output,
> regression-detection JSON storage). If this file ever conflicts with
> the Brief, the Brief wins.
>
> This item BUNDLES `@Metric` with `@Eval` because the Brief always
> shows them together and a metric-less `@Eval` is meaningless. AJ-5
> (whose original title was "@Metric decorator (custom metrics on
> agents)") is **cancelled/re-scoped** as a follow-up cleanup — its
> intended surface is delivered here.

## What

`@Eval` is a **class decorator** that turns a class into an evaluation
suite. The decorator:

1. Validates its configuration at decoration time (exactly one of
   `agent=` / `workflow=` set, `dataset=` coercible via
   `resolve_dataset`, `threshold` and `concurrency` typed and
   in-range).
2. Discovers `@Metric`-decorated methods on the class.
3. Stamps `_ajolopy_eval` metadata (target, dataset spec, threshold,
   concurrency, metric bindings) and stays inert. No dataset open, no
   agent invocation, no span emission until a runner calls `.run(cls)`.

`@Metric` is a **method decorator** that marks a method on an `@Eval`
class as a metric. Each metric receives `(self, output: EvalOutput,
expected: Mapping[str, Any]) -> float` and contributes a value per
case. Per-metric `aggregator`, `weight`, and `pass_threshold` kwargs
configure aggregation and pass/fail semantics.

`EvalRunner.run(suite_cls)` is the programmatic API the CLI (AJ-35)
will wrap:

1. Resolve the dataset via `resolve_dataset` (AJ-25).
2. Instantiate the suite class (`Cls()`, zero-arg) once per `run()`.
3. For each `Case` in the dataset (up to `concurrency` in flight):
   a. Build an `EvalOutput` by invoking
      `await target.run(**case.input)` and capturing latency / cost /
      trace ID.
   b. Call each `@Metric` method with `(self_instance, output,
      case.expected)` and collect floats.
   c. Capture errors per case (`agent.run()` raises → metrics
      skipped → case marked failed).
4. Aggregate per-metric values via the configured aggregator.
5. Compute weighted aggregate score and compare against
   `Eval.threshold`.
6. Return an `EvalRun` dataclass with everything captured.

`EvalRun` is the regression-detection unit. `EvalRun.save(path)` writes
a rich JSON snapshot to `.ajolopy/eval-runs/<timestamp>.json`;
`EvalRun.load(path)` reads it back; `compare_runs(prev, curr) ->
EvalComparison` produces a diff (per-metric deltas + newly-failing
case ids). AJ-27 will wire `ajolopy eval --compare-with` on top.

## Why

Brief v4.0 §"7 dolores ancla" calls out dolor #3 explicitly: "Modelo
nuevo + evals que no tenías bajan en silencio → `ajolopy eval
--compare-with` muestra delta + casos newly-failing. Block del PR si
threshold cae". `@Eval` is the on-ramp; without it the Brief's Paso 2
of the killer demo cannot be told. The wedge user (AI Engineer at a
Series A) curates JSONL fixtures, declares `@Eval` over an existing
agent / workflow, and gets:

- A repeatable score per change.
- Per-metric thresholds for safety / latency / correctness.
- Run snapshots for `--compare-with` regression catches.
- OTel spans visible in Langfuse / Honeycomb like any other
  agent invocation.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: drop `@Eval(agent=X, dataset="evals/x.jsonl")` on
  a class with `@Metric` methods. `EvalRunner` defaults to
  concurrency=5, threshold=0.5, mean aggregator, per-metric
  pass_threshold=0.5. Score appears, threshold is checked, run is
  saved.
- **Escape hatch**: subclass `EvalRunner` (override `_invoke_target`
  for custom invocation, `_aggregate` for custom score combinators) or
  build cases programmatically and call the runner directly.

## Public surface (v0.1)

```python
from ajolopy.eval import Eval, Metric, EvalRunner

@Eval(agent=Support, dataset="evals/support.jsonl", threshold=0.85)
class SupportEval:
    """Smoke test for the Support agent."""

    @Metric
    def helpful(self, output, expected) -> float:
        return 1.0 if expected["intent"] in output.text.lower() else 0.0

    @Metric(aggregator="min", pass_threshold=1.0)
    def safe(self, output, expected) -> float:
        return 0.0 if "api_key" in output.text else 1.0

    @Metric(aggregator="p95", weight=0.5)
    def latency_ms(self, output, expected) -> float:
        return max(0.0, 1.0 - output.latency_ms / 5000)


run = await EvalRunner().run(SupportEval)
run.save(".ajolopy/eval-runs/2026-05-14T22-30-00Z.json")
```

### Decorator signatures

```python
def Eval(
    *,
    agent: type | None = None,
    workflow: type | None = None,
    dataset: str | os.PathLike[str] | Dataset | type[Dataset],
    threshold: float = 0.5,
    concurrency: int = 5,
) -> Callable[[type[T]], type[T]]: ...


@overload
def Metric(fn: Callable[..., float], /) -> Callable[..., float]: ...
@overload
def Metric(
    *,
    aggregator: Literal["mean", "min", "max", "p50", "p95", "count_passing"] = "mean",
    weight: float = 1.0,
    pass_threshold: float = 0.5,
) -> Callable[[Callable[..., float]], Callable[..., float]]: ...
```

- **`Eval`** — exactly one of `agent=` / `workflow=` is required. Both
  set OR neither set → `EvalConfigError` at decoration time.
- **`dataset`** — anything `resolve_dataset` accepts (AJ-25).
- **`threshold`** — float in `[0.0, 1.0]`. `EvalConfigError` otherwise.
- **`concurrency`** — int `>= 1`. `EvalConfigError` otherwise.
- **`Metric`** — bare-form `@Metric` (no parens) AND parameterised
  form `@Metric(aggregator="...", weight=..., pass_threshold=...)`
  both work. The bare form is the common case.
- **Method shape** — `def helpful(self, output, expected) -> float:`.
  Sync OR async; async metrics are awaited. Return is coerced to
  `float`; non-numeric returns raise `MetricRuntimeError` per case.

### Result dataclasses

```python
@dataclass(slots=True, frozen=True)
class EvalOutput:
    text: str
    latency_ms: float
    cost_usd: float | None
    trace_id: str | None
    raw: object   # the raw return of target.run(); typed as object so metrics can cast


@dataclass(slots=True, frozen=True)
class EvalCaseResult:
    case_index: int           # 0-based position in dataset
    input: Mapping[str, Any]
    expected: Mapping[str, Any]
    output: EvalOutput | None
    metric_scores: Mapping[str, float]   # metric name → raw score for this case
    error: str | None         # str(exc) when target.run() or a metric raised
    passed: bool              # all metrics passed_threshold AND no error


@dataclass(slots=True, frozen=True)
class EvalMetricResult:
    name: str
    aggregator: str           # one of the six
    weight: float
    pass_threshold: float
    values: tuple[float, ...] # per-case raw values, in dataset order
    aggregate: float
    passed: bool              # aggregate >= pass_threshold


@dataclass(slots=True, frozen=True)
class EvalRun:
    suite: str                # class.__name__
    timestamp: str            # ISO 8601 UTC, e.g. "2026-05-14T22:30:00Z"
    target_kind: Literal["agent", "workflow"]
    target_name: str          # the agent/workflow class name
    dataset_path: str | None  # absolute string path; None for in-memory datasets
    dataset_sha256: str | None  # sha256 of the dataset file contents; None for in-memory
    threshold: float
    concurrency: int
    metrics: Mapping[str, EvalMetricResult]
    cases: tuple[EvalCaseResult, ...]
    aggregate_score: float    # weighted aggregate
    passed: bool              # aggregate_score >= threshold

    def save(self, path: str | os.PathLike[str]) -> Path: ...
    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "EvalRun": ...


@dataclass(slots=True, frozen=True)
class EvalComparison:
    suite: str
    prev_timestamp: str
    curr_timestamp: str
    metric_deltas: Mapping[str, MetricDelta]
    newly_failing_case_indices: tuple[int, ...]
    newly_passing_case_indices: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class MetricDelta:
    name: str
    prev_aggregate: float
    curr_aggregate: float
    delta: float              # curr - prev
    is_regression: bool       # curr < prev (lower-is-worse semantics)
```

### `EvalRunner` API

```python
class EvalRunner:
    def __init__(
        self,
        *,
        eval_runs_dir: Path | None = None,    # defaults to .ajolopy/eval-runs/
    ) -> None: ...

    async def run(self, suite_cls: type) -> EvalRun: ...
```

`run(suite_cls)`:

1. Reads `_ajolopy_eval` metadata.
2. Calls `resolve_dataset(metadata.dataset)`.
3. Computes `dataset_sha256` (if the dataset has a `.path` attribute,
   reads the file and hashes it; else `None` — covers custom datasets
   without a backing file).
4. Instantiates `suite_cls()`.
5. Iterates cases concurrently with `asyncio.Semaphore(concurrency)`:
   for each case:
   - Builds an `EvalOutput` by invoking `await target.run(**case.input)`.
     Captures wall-clock latency, cost from
     `ajolopy.cost_usd.total` (via the `cost_sink` kwarg from AJ-6 if
     the target is an `@Agent`; via the corresponding workflow path
     otherwise), and the current `trace_id` from
     `opentelemetry.trace.get_current_span()`.
   - Runs each `@Metric` against the output. Sync / async / coerced
     `float` per spec; on error per metric, stores `metric_scores[name]
     = 0.0` and includes the metric name in the case's error field.
   - On target invocation error, captures `str(exc)` and skips all
     metrics for that case (their `values` entry for that case is
     `0.0`).
6. Aggregates each metric via its `aggregator`. `count_passing` uses
   the metric's own `pass_threshold` as the per-case bar.
7. Computes weighted aggregate score: `sum(m.weight * m.aggregate) /
   sum(m.weight)` across all metrics.
8. Builds the `EvalRun` and returns it.

`EvalRun.save(path)` serialises to JSON using the documented shape
(see "Run storage" below).

### Run storage format

`.ajolopy/eval-runs/<timestamp>.json` shape:

```json
{
  "schema_version": 1,
  "suite": "SupportEval",
  "timestamp": "2026-05-14T22:30:00Z",
  "target": {"kind": "agent", "name": "Support"},
  "dataset": {
    "path": "/abs/path/to/evals/support.jsonl",
    "sha256": "abc123..."
  },
  "threshold": 0.85,
  "concurrency": 5,
  "metrics": {
    "helpful": {
      "aggregator": "mean",
      "weight": 1.0,
      "pass_threshold": 0.8,
      "values": [0.9, 0.8, 1.0],
      "aggregate": 0.9,
      "passed": true
    }
  },
  "cases": [
    {
      "case_index": 0,
      "input": {"message": "where is my order?"},
      "expected": {"intent": "order_status"},
      "output": {
        "text": "Your order is in transit.",
        "latency_ms": 142.0,
        "cost_usd": 0.00012,
        "trace_id": "abc123",
        "raw_repr": "'Your order is in transit.'"
      },
      "metric_scores": {"helpful": 0.9},
      "error": null,
      "passed": true
    }
  ],
  "aggregate_score": 0.92,
  "passed": true
}
```

The `raw_repr` field on the output is a string repr (via `repr(raw)`)
for diagnostic display only — round-tripping the original `raw` value
is out of scope. `EvalRun.load(path)` reads JSON and reconstructs the
dataclass tree; the `raw` field on the loaded `EvalOutput` is the
string repr (not the original object) — clients that want full
fidelity should keep the in-memory `EvalRun`.

Directory creation: `eval_runs_dir` is created with `mkdir(parents=True,
exist_ok=True)` on the first `save()`. Default location is
`.ajolopy/eval-runs/` resolved against `os.getcwd()`.

### `compare_runs(prev, curr)` semantics

```python
def compare_runs(prev: EvalRun, curr: EvalRun) -> EvalComparison: ...
```

- **Suite name mismatch** → `EvalComparisonError`.
- **Dataset sha256 mismatch** → `EvalComparisonError("dataset changed
  between runs; comparisons are only meaningful for the same dataset")`.
  AJ-27's CLI will surface a `--force` flag later if needed.
- **Per-metric `metric_deltas`**: includes every metric present in
  EITHER run. Missing-in-prev → `prev_aggregate=NaN`, `is_regression=False`
  (new metric, not a regression).
- **`is_regression`**: `curr.aggregate < prev.aggregate - 0.001`
  (1e-3 floor for float noise).
- **`newly_failing_case_indices`**: indices that `passed=True` in
  `prev` and `passed=False` in `curr`. Ordered ascending.
- **`newly_passing_case_indices`**: the inverse direction.
- Case count mismatch (dataset trimmed) → `EvalComparisonError`.

### Observability

Spans (always-on, mirrors AJ-28):

```
eval.run {SuiteName}                           ← root, one per EvalRunner.run() call
├── eval.case {case_index}                     ← one per case
│   └── (whatever the underlying target emits: workflow.invoke /
│        agent.invoke etc.)
└── eval.case {case_index+1}
    └── ...
```

New attribute constants (in `ajolopy.observability.conventions`):

| Attribute                       | Where         | Value                                  |
|---------------------------------|---------------|----------------------------------------|
| `ajolopy.eval.suite`            | `eval.run`    | suite class name                       |
| `ajolopy.eval.target_kind`      | `eval.run`    | `"agent"` or `"workflow"`              |
| `ajolopy.eval.threshold`        | `eval.run`    | configured aggregate threshold          |
| `ajolopy.eval.aggregate_score`  | `eval.run`    | final weighted aggregate                |
| `ajolopy.eval.passed`           | `eval.run`    | overall boolean                        |
| `ajolopy.eval.concurrency`      | `eval.run`    | configured concurrency cap             |
| `ajolopy.eval.case_index`       | `eval.case`   | 0-based dataset index                  |
| `ajolopy.eval.case_passed`      | `eval.case`   | per-case boolean                       |
| `ajolopy.eval.case_error`       | `eval.case`   | str(exc) when present                   |
| `ajolopy.eval.score.<metric>`   | `eval.case`   | per-metric per-case raw float          |

Cost roll-up: each `eval.case` span reuses the existing
`ajolopy.cost_usd.total` from the underlying agent/workflow span. The
`eval.run` root span sums those values into its own
`ajolopy.cost_usd.total`. Reuses the `set_root_cost_total` helper from
AJ-30 with a workflow-style sink pattern.

### Cancellation

`asyncio.CancelledError` from above the runner propagates: in-flight
cases see their inner `await` cancelled, and the runner re-raises so
the CLI / test harness sees the cancel. Partially-completed `EvalRun`
state is NOT persisted — `save()` only runs when the full suite
finishes successfully. (AJ-35 will decide whether to surface a
`--save-on-cancel` flag later.)

## Design rules

- **Magical default**: a class with `@Eval` + a few `@Metric` methods
  produces a meaningful report with zero ceremony. All kwargs have
  defaults; the only required ones are `agent=`/`workflow=` and
  `dataset=`.
- **Escape hatches**:
  - Subclass `EvalRunner` for custom invocation / aggregation.
  - Implement `Dataset` (AJ-25) for non-JSONL sources.
  - Build the suite programmatically by instantiating the metadata
    dataclasses (no decoration required) for runtime-generated
    suites.
- **Storage is opt-in at `run()` level**: `EvalRun` is returned in
  memory always; `.save()` is the caller's choice. AJ-35's CLI will
  call it by default; programmatic users who just want a quick
  score skip it.
- **Per-case isolation**: a tool error / metric exception fails just
  that case; the suite continues. The Brief calls out "block del PR
  si threshold cae" — partial failures still produce a usable
  `EvalRun` so the caller can decide.
- **Deterministic ordering**: cases run with bounded concurrency but
  results land in `EvalRun.cases` ordered by `case_index` so reruns
  are stable and `compare_runs` is well-defined.

## Out of scope for this item

- **Built-in metrics library** (`exact_match`, `llm_judge`,
  `tool_called`, `intent_match`, `contains`) → AJ-26.
- **`ajolopy eval` CLI subcommand** → AJ-35. AJ-4 ships only the
  programmatic `EvalRunner` + result types.
- **`--compare-with` CLI flag** → AJ-27. AJ-4 ships only the
  `EvalRun.save/load` + `compare_runs` primitive.
- **`--dry-run` cost estimation** → AJ-35.
- **Run retention policy** (auto-delete old runs) → not in v0.1.
- **OTel meters / custom metric API** (`metric.timer/counter/gauge`)
  → AJ-31.
- **Distributed eval runners** (Run across N workers) → v0.2.
- **Eval reports / HTML output** → v0.2.
- **LLM-as-judge result caching** → v0.2 (likely via AJ-26 once
  built-ins land).

## Acceptance criteria

Each item must have at least one passing test. **Targets are mocked**
at the `target.run()` boundary; no real LLM calls in CI. Tests for
async / sync `@Metric` use plain callables, not the full provider
machinery.

### `@Eval` decoration-time validation

- [x] `@Eval(agent=Support, dataset="x.jsonl")` on a class with at
      least one `@Metric` stamps `_ajolopy_eval` metadata and
      preserves the class type for pyright.
- [x] `@Eval(workflow=SupportTeam, dataset="x.jsonl")` works
      similarly.
- [x] `@Eval(agent=A, workflow=B, dataset=...)` raises
      `EvalConfigError` (exactly-one rule).
- [x] `@Eval(dataset=...)` with neither `agent=` nor `workflow=`
      raises `EvalConfigError`.
- [x] `@Eval(agent=Plain, dataset=...)` where `Plain` is not
      `@Agent`-decorated raises `EvalConfigError`.
- [x] `@Eval(workflow=Plain, dataset=...)` where `Plain` is not
      `@Workflow`-decorated raises `EvalConfigError`.
- [x] `@Eval(agent=A, dataset=...)` with NO `@Metric` methods raises
      `EvalConfigError` ("an Eval suite needs at least one @Metric
      method").
- [x] `@Eval(threshold=-0.1)` and `threshold=1.1` raise
      `EvalConfigError`.
- [x] `@Eval(concurrency=0)` and `concurrency=-1` raise
      `EvalConfigError`.
- [x] An invalid `dataset=` form bubbles `DatasetError` (re-raised
      with context, not as `EvalConfigError`).

### `@Metric` decoration-time validation

- [x] `@Metric` (bare) on `def helpful(self, output, expected) ->
      float:` stamps `_ajolopy_metric` metadata with default
      `aggregator="mean"`, `weight=1.0`, `pass_threshold=0.5`.
- [x] `@Metric(aggregator="p95", weight=0.5, pass_threshold=0.8)`
      stamps the supplied values.
- [x] `@Metric(aggregator="bogus")` raises `MetricConfigError`
      listing the six accepted aggregators.
- [x] `@Metric(weight=-1)` and `weight=0` raise
      `MetricConfigError`.
- [x] `@Metric(pass_threshold=2.0)` and `pass_threshold=-0.1` raise
      `MetricConfigError`.
- [x] Method signature mismatch (less than 3 positional args
      including `self`) at decoration time raises
      `MetricConfigError` with a hint pointing at the documented
      `(self, output, expected)` shape.
- [x] Two `@Metric`-decorated methods with the same `__name__` on
      the same `@Eval` class raise `EvalConfigError` ("duplicate
      metric name 'X'").

### Dataclass invariants

- [x] `Case` (reused from AJ-25), `EvalOutput`, `EvalCaseResult`,
      `EvalMetricResult`, `EvalRun`, `MetricDelta`, `EvalComparison`
      are all frozen + slotted dataclasses.
- [x] `EvalOutput.text` is always a string; non-string return from
      `target.run()` is coerced via `str(raw)` and the original
      stored under `.raw`.
- [x] `EvalCaseResult.passed == False` whenever `error is not None`.

### `EvalRunner.run()` — happy paths

- [x] With a mocked agent that returns a fixed text per case and a
      single `@Metric` returning 1.0, the run produces
      `aggregate_score=1.0` and `passed=True`.
- [x] With `threshold=0.9` and a metric that returns 0.5 for every
      case, the run produces `passed=False`.
- [x] All six aggregators (`mean`, `min`, `max`, `p50`, `p95`,
      `count_passing`) produce the expected value on a fixed input
      sequence (verified against `statistics` module results).
- [x] `count_passing` uses each metric's own `pass_threshold` as the
      per-case bar.
- [x] Weighted aggregate equals
      `sum(m.weight * m.aggregate) / sum(m.weight)` across metrics.
- [x] Concurrency cap: with `concurrency=2` and a target that
      `await asyncio.sleep(0.05)`, the runner completes 6 cases in
      `~3 * 0.05 s` (verified with a tolerance band).
- [x] Per-case `case_index` corresponds to dataset order
      regardless of concurrency.
- [x] Async `@Metric` (e.g. `llm_judge`-style) is awaited.
- [x] `target.run()` for `@Agent` is called with `**case.input`;
      same for `@Workflow`.

### `EvalRunner.run()` — error paths

- [x] `target.run()` raising sets `case.error`, `case.passed=False`,
      `case.output=None`, all `metric_scores=0.0`, and the suite
      continues for the remaining cases.
- [x] A `@Metric` raising sets just that metric's score to 0.0 for
      that case and includes the metric name in the case's `error`
      field; other metrics still run for the same case.
- [x] A non-numeric `@Metric` return raises `MetricRuntimeError`
      caught into the case's error.
- [x] An empty dataset (zero cases) raises `EvalRunError("dataset
      has no cases")` — refusing to compute against an empty input
      avoids divide-by-zero on aggregations.

### `EvalRun.save` / `EvalRun.load`

- [x] `save()` writes JSON matching the documented schema; reading
      with `json.load` produces a dict with the documented keys.
- [x] Default location is `.ajolopy/eval-runs/<timestamp>.json`;
      directory is created on first save.
- [x] Timestamp follows ISO 8601 UTC with `Z` suffix.
- [x] `load(path)` round-trips `aggregate_score`, `passed`,
      per-metric aggregations, and per-case `passed` / `error`.
- [x] `EvalRun.load(path).cases[N].output.raw` is the string repr
      (not the original object) per the documented limitation.
- [x] Schema version mismatch (`schema_version != 1`) raises
      `EvalRunError("unsupported eval-run schema version")`.

### `compare_runs(prev, curr)`

- [x] Equal runs produce `MetricDelta` with `delta=0` and
      `is_regression=False` for every metric.
- [x] A metric whose aggregate dropped by 0.05 reports
      `is_regression=True`.
- [x] A metric whose aggregate dropped by 0.0005 (below 1e-3 floor)
      reports `is_regression=False`.
- [x] Cases that flipped `passed=True` → `False` appear in
      `newly_failing_case_indices` in ascending order.
- [x] Cases that flipped `passed=False` → `True` appear in
      `newly_passing_case_indices`.
- [x] Suite-name mismatch raises `EvalComparisonError`.
- [x] Dataset sha256 mismatch raises `EvalComparisonError`.
- [x] Case-count mismatch raises `EvalComparisonError`.

### Observability

- [x] One `eval.run {Suite}` span per `EvalRunner.run()` call with
      `ajolopy.eval.suite`, `target_kind`, `threshold`,
      `aggregate_score`, `passed`, `concurrency` attributes.
- [x] One `eval.case {i}` span per case with
      `ajolopy.eval.case_index`, `case_passed`, `case_error`
      (when present), and one `ajolopy.eval.score.<metric>` attr
      per metric.
- [x] The `eval.run` span carries `ajolopy.cost_usd.total` equal to
      the sum of per-case costs (verified with a fake catalog).
- [x] `eval.case` spans nest under `eval.run` so the trace
      hierarchy is preserved when exporters render it.

### Public re-exports

- [x] `from ajolopy.eval import (Eval, Metric, EvalRunner,
      EvalOutput, EvalCaseResult, EvalMetricResult, EvalRun,
      EvalComparison, MetricDelta, compare_runs, EvalConfigError,
      EvalRunError, EvalComparisonError, MetricConfigError,
      MetricRuntimeError)` works.
- [x] `ajolopy.eval.__all__` is updated.
- [x] `Eval`, `Metric` are added to `src/ajolopy/__init__.py`
      `__all__` alongside the other primitive decorators (a
      consistent rule: top-level primitives stay at the top level).

## Implementation pointers

- Source (extends the existing `src/ajolopy/eval/` from AJ-25):
  - `eval_decorator.py` — `@Eval` factory + metadata stamping +
    decoration-time validation. Named with the `_decorator` suffix
    because `eval` is a reserved Python builtin.
  - `metric.py` — `@Metric` factory (overload-typed: bare + parens
    form) + `MetricMetadata` dataclass + `discover_metrics(cls)`.
  - `results.py` — `EvalOutput`, `EvalCaseResult`, `EvalMetricResult`,
    `EvalRun`, `MetricDelta`, `EvalComparison` dataclasses.
  - `aggregators.py` — the six aggregator functions keyed by name.
  - `runner.py` — `EvalRunner` + the concurrent run engine + cost /
    latency / trace capture.
  - `storage.py` — `EvalRun.save` + `EvalRun.load` + schema version
    constant + dataset sha256 helper.
  - `comparison.py` — `compare_runs(prev, curr) -> EvalComparison`.
  - `errors.py` — extends the existing `errors.py` with
    `EvalConfigError`, `EvalRunError`, `EvalComparisonError`,
    `MetricConfigError`, `MetricRuntimeError`.
  - `__init__.py` — public re-exports.
- Cross-cut to `src/ajolopy/observability/conventions.py`:
  - New helpers `eval_run_span_name(suite)`, `eval_case_span_name(idx)`.
  - New attribute constants `AJOLOPY_EVAL_SUITE`,
    `AJOLOPY_EVAL_TARGET_KIND`, `AJOLOPY_EVAL_THRESHOLD`,
    `AJOLOPY_EVAL_AGGREGATE_SCORE`, `AJOLOPY_EVAL_PASSED`,
    `AJOLOPY_EVAL_CONCURRENCY`, `AJOLOPY_EVAL_CASE_INDEX`,
    `AJOLOPY_EVAL_CASE_PASSED`, `AJOLOPY_EVAL_CASE_ERROR`.
  - The per-metric `ajolopy.eval.score.<name>` is built dynamically
    (no constant); just document the prefix.
- Cross-cut to `src/ajolopy/__init__.py`:
  - Add `Eval` and `Metric` to `__all__` next to the other
    primitives. NO other surface lands at top level (the result
    dataclasses + runner stay under `ajolopy.eval`).
- Reuse without modification:
  - `Dataset`, `Case`, `resolve_dataset` from AJ-25.
  - `AgentRuntime`'s `cost_sink` kwarg from AJ-6.
  - `WorkflowRuntime`'s same `cost_sink` plumbing (the runner passes
    a per-case list into either target).
  - `chat_span_name` / `set_root_cost_total` from AJ-30.
- Tests: `tests/eval/` (extends existing AJ-25 directory).
  - `test_eval_decorator_validation.py`
  - `test_metric_decorator.py`
  - `test_aggregators.py`
  - `test_runner_happy.py`
  - `test_runner_errors.py`
  - `test_concurrency.py`
  - `test_storage.py`
  - `test_compare_runs.py`
  - `test_observability.py`
  - `test_public_api.py` (extends the AJ-25 file).
- Runtime deps: none new. `statistics` is stdlib for aggregators;
  `hashlib` stdlib for sha256.

## Implementation notes

### Cost capture for workflow targets

The runner threads `cost_sink=` into `AgentRuntime.run` for agent
targets and reads the per-case cost from the accumulator. The
`@Workflow` runtime does NOT expose the same kwarg on its public
`run(message, **context)` API (the workflow already owns a child
`agent.invoke` span that carries its own `ajolopy.cost_usd.total`
roll-up). Workflow-target cases therefore record `cost_usd=None` in
the `EvalOutput`. The `eval.run` span's `ajolopy.cost_usd.total` is
the sum over non-`None` per-case costs, which means agent targets
roll up cleanly while workflow targets omit the attribute when every
case used a workflow path. Deeper workflow-side cost wiring is
deferred to AJ-31.

### Case-span nesting under `asyncio.gather`

Python's asyncio propagates contextvars across `await`/`gather`, but
the propagation snapshot is taken at `gather()` time — workers
scheduled later can race with the run-span's `start_as_current_span`
entering its context. The runner pins the parent context explicitly
via `opentelemetry.trace.use_span(run_span, end_on_exit=False)` inside
each worker before opening its `eval.case` span. The
`end_on_exit=False` is load-bearing: without it the run span would
end when the first worker leaves its case body.

### Per-metric `passed` and `count_passing`

The two pass/fail dimensions are independent:

- **Per-case, per-metric pass** — `score >= metric.pass_threshold`.
  Used as the per-case `EvalCaseResult.passed` conjunct.
- **Per-suite, per-metric pass** — `aggregate >= metric.pass_threshold`.
  Used as `EvalMetricResult.passed`.

For `count_passing` the aggregate IS the fraction of cases that
cleared `pass_threshold`, so the per-suite check reads naturally as
"at least `pass_threshold` of cases pass". The two semantics happen
to share the same threshold field by design — having one number do
both jobs keeps the surface tight (single setting per metric instead
of "case threshold + suite threshold + count_passing threshold").

### Dataclass save/load — methods, not late binding

The original plan was to bind `save`/`load` onto :class:`EvalRun` at
import time from :mod:`storage`. That trips pyright's
`reportAttributeAccessIssue` everywhere :class:`EvalRun.save` /
:meth:`EvalRun.load` is called. The final wire-up declares both as
plain methods on the dataclass with a lazy `from .storage import …`
inside the body; pyright sees them statically, storage stays the only
module that touches :mod:`json` / :mod:`pathlib`, and result-module
import remains cheap.

### CodeQL false-positive mitigations applied

- `@Eval` uses a manual `TypeVar("T")` (not PEP 695 `def Eval[T]`)
  because the decorator runs pre-`_decorate` validation that may
  raise. PEP 695 would trip "Potentially uninitialized local
  variable" in the same way `@MCP` did pre-AJ-7 cleanup.
- Aggregator type alias `Aggregator` is a classic
  `Aggregator = Callable[[...], float]` assignment (not PEP 695
  `type Aggregator = …`) so the re-export from
  :mod:`ajolopy.eval.aggregators.__all__` does not trip "Explicit
  export is not defined".
- The runner does NOT declare an unused `_LOGGER = logging.getLogger(...)`
  module-level constant. CodeQL flags those as "Unused global
  variable"; future logging needs (e.g. per-case warnings) will
  introduce the logger together with its first call site.
