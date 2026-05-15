# `@Eval` + `@Metric`

!!! note "Spec"
    Full specification: [`specs/eval.md`](https://github.com/jcocano/ajolopy/blob/main/specs/eval.md)
    · Item: `AJ-4` (bundles `@Metric`, originally tracked as `AJ-5`)

## Purpose

`@Eval` is a class decorator that turns a class into an evaluation suite
over an [`@Agent`](agent.md) or [`@Workflow`](workflow.md) target.
`@Metric` is the companion method decorator that marks per-case
scoring functions. The two ship together because a metric-less `@Eval`
is meaningless.

`EvalRunner.run(SuiteCls)` resolves the dataset, instantiates the target,
runs cases concurrently, aggregates per-metric scores via the configured
aggregator (`mean` / `min` / `max` / `p50` / `p95` / `count_passing`),
computes a weighted total, compares against `threshold`, and returns an
`EvalRun` snapshot. `EvalRun.save(...)` + `compare_runs(prev, curr)`
power regression detection ([the AJ-27 CLI](https://github.com/jcocano/ajolopy/blob/main/board.json) wraps this).

Reach for `@Eval` whenever you change a prompt, a model, or a tool — and
you want a number to decide whether to ship.

## Signature

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

## Quick example

```python
from ajolopy import Agent
from ajolopy.eval import Eval, EvalRunner, Metric


@Agent(model="claude-sonnet-4-7", system="You are Acme Support.")
class Support:
    """Top-level support agent."""


@Eval(agent=Support, dataset="evals/support.jsonl", threshold=0.85)
class SupportEval:
    """Smoke test for the Support agent."""

    @Metric
    def helpful(self, output, expected) -> float:
        return 1.0 if expected["intent"] in output.text.lower() else 0.0

    @Metric(aggregator="p95", weight=0.5)
    def latency(self, output, expected) -> float:
        return max(0.0, 1.0 - output.latency_ms / 5000)


async def main() -> None:
    run = await EvalRunner().run(SupportEval)
    run.save(".ajolopy/eval-runs/2026-05-14T22-30-00Z.json")
```

## Kwargs

| Decorator  | Kwarg            | Type                                                                                 | Default   | Description |
|------------|------------------|--------------------------------------------------------------------------------------|-----------|-------------|
| `@Eval`    | `agent`          | `type \| None`                                                                       | `None`    | An `@Agent` class. Exactly one of `agent=` / `workflow=` is required. |
| `@Eval`    | `workflow`       | `type \| None`                                                                       | `None`    | A `@Workflow` class. Mutually exclusive with `agent=`. |
| `@Eval`    | `dataset`        | `str \| PathLike \| Dataset \| type[Dataset]`                                        | required  | Anything `resolve_dataset` accepts (path to JSONL, custom `Dataset`, ...). |
| `@Eval`    | `threshold`      | `float`                                                                              | `0.5`     | Aggregate-score floor in `[0.0, 1.0]`. The suite passes when the weighted aggregate clears it. |
| `@Eval`    | `concurrency`    | `int`                                                                                | `5`       | Max in-flight cases per `run()`. Must be `>= 1`. |
| `@Metric`  | `aggregator`     | `Literal["mean", "min", "max", "p50", "p95", "count_passing"]`                       | `"mean"`  | How per-case scores fold into the metric's aggregate. |
| `@Metric`  | `weight`         | `float`                                                                              | `1.0`     | Relative weight in the suite-wide weighted aggregate. Must be `> 0`. |
| `@Metric`  | `pass_threshold` | `float`                                                                              | `0.5`     | Per-case pass bar AND per-metric aggregate pass bar (shared by design). |

## Escape hatches

- **Subclass `EvalRunner`** to override `_invoke_target` (custom
  invocation flow) or `_aggregate` (custom score combinators).
- **Programmatic suites.** Build `_ajolopy_eval` metadata by hand for
  runtime-generated suites that do not fit the decorator surface.
- **Custom datasets.** Implement `Dataset` (see [`specs/dataset-loader.md`](https://github.com/jcocano/ajolopy/blob/main/specs/dataset-loader.md))
  for non-JSONL sources (CSV, S3, in-memory generators, ...).
- **Async metrics.** `@Metric` accepts `async def` for LLM-as-judge or
  network-bound scoring.

## Common gotchas

- Exactly one of `agent=` / `workflow=` must be set. Both or neither
  raises `EvalConfigError` at decoration time.
- A suite without any `@Metric` method raises `EvalConfigError` — an
  eval with no metrics has nothing to measure.
- Per-case isolation: a target error or metric exception fails just
  that case; the suite continues. `EvalRun.passed` reflects the
  aggregate.
- `compare_runs(prev, curr)` rejects dataset sha256 mismatches with
  `EvalComparisonError` — comparisons are only meaningful for the same
  dataset.
- `EvalRun.load(path).cases[i].output.raw` is the **string repr** of
  the original return, not the original object. Round-tripping full
  fidelity is out of scope; keep the in-memory `EvalRun` if you need
  the raw value.

## See also

- [`@Agent`](agent.md) / [`@Workflow`](workflow.md) — the targets an
  eval suite scores.
- Spec: [`specs/eval.md`](https://github.com/jcocano/ajolopy/blob/main/specs/eval.md).
- Dataset format: [`specs/dataset-loader.md`](https://github.com/jcocano/ajolopy/blob/main/specs/dataset-loader.md).
