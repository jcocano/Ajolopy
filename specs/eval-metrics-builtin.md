# AJ-26 — Built-in metrics library for `@Eval`

> Tracked in [`board.json`](../board.json) as `AJ-26`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth: Brief v4.0 §"Killer demo Paso 2" + `09 - Eval framework`
> §"Métricas comunes built-in" and §"LLM-as-judge". If this file ever
> conflicts with the Brief, the Brief wins. AJ-26 ships ALL SEVEN
> helpers the Brief lists (the board title is out of date — fixed in
> this PR's chore commit).

## What

`ajolopy.eval.metrics` is a new sub-package shipping seven helper
functions that `@Metric`-decorated methods call. Each helper takes an
`EvalOutput` (or a derived string) plus an `expected` value and returns
a `float` in `[0.0, 1.0]`. The helpers are NOT metrics themselves — the
user wraps them in their own `@Metric` method on an `@Eval` suite.

The seven helpers:

| Helper          | Signature                                                  | Sync/async |
|-----------------|------------------------------------------------------------|------------|
| `exact_match`   | `(output, expected) -> float`                              | sync       |
| `json_match`    | `(output, expected) -> float`                              | sync       |
| `contains`      | `(text, needles) -> float`                                 | sync       |
| `not_contains`  | `(text, needles) -> float`                                 | sync       |
| `intent_match`  | `(output, intent) -> float`                                | sync       |
| `tool_called`   | `(output, tool_name) -> float`                             | sync       |
| `llm_judge`     | `(output, *, criterion, model, expected=None, scale="0-1", cache=False, provider=None) -> float` | async      |

`tool_called` requires a small extension to `EvalOutput`: a new
`tool_calls: tuple[str, ...]` field carrying the names of tools the
agent invoked during the case. AJ-4's `EvalOutput`, `AgentRuntime`, the
runner, and storage layer all gain a thin pass-through for this list.
Workflow-target cases get `tool_calls=()` in v0.1 (deeper workflow-side
tool capture is left to AJ-31 / a future workflow instrumentation
pass).

`llm_judge` calls an `LLMProvider` (AJ-18) with a synthesised judge
prompt and parses the response back to a float. An in-memory
sha256-keyed cache is opt-in via `cache=True`; the default `cache=False`
matches the rest of the framework's "no hidden global state" rule.

## Why

Brief v4.0 §"Métricas comunes built-in" enumerates the seven helpers
and shows them used inside `@Metric` bodies. Without them, AJ-4's
`@Eval` is technically usable but every user has to hand-roll the same
"did the agent say X?" / "did the JSON look right?" / "is this answer
helpful?" checks per project — exactly the duct-tape Ajolopy is
supposed to delete. The wedge user (AI Engineer at a Series A startup)
reaches for `llm_judge` the moment "exact match" stops fitting and for
`tool_called` the moment they want to verify the agent reached the
right side-effect.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: import the helper and call it. Sensible defaults
  for case-insensitivity, partial scoring, model selection.
- **Escape hatch**: every helper is a plain function — wrap your own
  metric in a `@Metric` method with whatever logic you need; the
  built-ins compose freely.

## Public surface (v0.1)

```python
from ajolopy import Eval, Metric
from ajolopy.eval.metrics import (
    contains,
    exact_match,
    intent_match,
    json_match,
    llm_judge,
    not_contains,
    tool_called,
)


@Eval(agent=Support, dataset="evals/support.jsonl", threshold=0.85)
class SupportEval:
    @Metric
    def correct_intent(self, output, expected) -> float:
        return intent_match(output, expected["intent"])

    @Metric
    def used_right_tool(self, output, expected) -> float:
        return tool_called(output, expected["tool"])

    @Metric
    def no_secrets_leaked(self, output, expected) -> float:
        return not_contains(output.text, ["api_key", "password", "ssn"])

    @Metric(aggregator="mean", pass_threshold=0.8)
    async def helpful(self, output, expected) -> float:
        return await llm_judge(
            output,
            expected=expected.get("ideal"),
            criterion="Does the response correctly address the user's question?",
            model="claude-sonnet-4-7",
            cache=True,
        )
```

### `exact_match(output, expected) -> float`

- Coerces `output` → text via the same `EvalOutput.text` rule
  (`output.text` if `EvalOutput`, otherwise `str(output)`).
- Coerces `expected` → text via `str(expected)`.
- Strips leading/trailing whitespace on both.
- Returns `1.0` on equality, else `0.0`.
- Case-sensitive by default; pass `case_insensitive=True` to lowercase
  both sides first.

### `json_match(output, expected) -> float`

- Treats `output` as JSON text (`output.text` when `EvalOutput`, else
  `str(output)`).
- Parses with `json.loads`. Parse failure → `0.0` (NOT a raise: a
  malformed-JSON output is just "doesn't match").
- Compares structurally with `==` against `expected` (which may be a
  dict / list / scalar — anything JSON-comparable).
- Returns `1.0` if equal, else `0.0`.
- v0.1 is strict (whole-object equality). A `partial=True` kwarg is
  reserved for v0.2 and rejected at call time with `MetricsConfigError`.

### `contains(text, needles) -> float`

- `text`: a `str` OR an `EvalOutput` (in which case `output.text` is
  used).
- `needles`: a `str` OR a `Sequence[str]`.
- Returns `1.0` if `mode="any"` (default) and AT LEAST ONE needle is in
  the text. `mode="all"` requires every needle.
- Case-insensitive by default (`case_sensitive=False`). Override via
  kwarg.
- Empty `needles` list → `MetricsConfigError("contains: needles is empty")`.

### `not_contains(text, needles) -> float`

Same surface as `contains` but inverted. Returns `1.0` if NO needle is
present (with `mode="any"`) — useful for safety checks
(`not_contains(output.text, ["api_key", "password"])`).

### `intent_match(output, intent) -> float`

Deterministic heuristic (no LLM call):

- Lowercases both sides.
- `intent` is `str` or `Sequence[str]`. Multi-intent: any-of match.
- Match strategy: substring (lowercased intent string appears anywhere
  in lowercased output text).
- Returns `1.0` if at least one intent matches; else `0.0`.
- A `mode="exact"` kwarg makes the comparison strict equality on the
  whole text (mirrors `exact_match` but multi-intent-aware).

### `tool_called(output, tool_name) -> float`

Reads `output.tool_calls` (the new field — see "Cross-cuts" below):

- `tool_name=None` → returns `1.0` if NO tools were called (useful for
  "this question should NOT trigger a tool").
- `tool_name=str` → returns `1.0` if the named tool appears in
  `output.tool_calls`; else `0.0`.
- `tool_name=Sequence[str]` → returns `1.0` if ANY of the named tools
  was called (with `mode="any"`, default) or if ALL were called
  (`mode="all"`).
- `output` must be an `EvalOutput`; passing a plain string raises
  `MetricsConfigError("tool_called requires an EvalOutput (got str)")`.

### `llm_judge(output, *, criterion, model, expected=None, scale="0-1", cache=False, provider=None) -> float`

Async. Builds a judge prompt, calls an LLM, parses the response back
to a float.

- `output` — `EvalOutput` (uses `.text`) or `str`.
- `criterion` — required. The yes/no question or scoring rubric the
  judge applies.
- `model` — required. Resolved through the AJ-18 provider registry.
- `expected` — optional. When provided, included in the judge prompt
  as "ideal response" guidance.
- `scale` — `"0-1"` (default) or `"1-5"` (Likert). The framework
  parses + rescales to `[0, 1]`.
- `cache` — opt-in. `False` by default. When `True`, an in-memory dict
  keyed by `sha256(criterion, output_text, expected_text, model,
  scale)` short-circuits repeated calls within the same process.
- `provider` — optional `LLMProvider` instance for testing /
  alternative providers; default resolves via the registry.

**Prompt template (v0.1, internal):**

```
You are an evaluation judge. Given an output and a criterion, score the
output on the scale {scale}. {scale_explanation}

Criterion: {criterion}

{expected_block}  # included only when expected is not None

Output to score:
\"\"\"
{output_text}
\"\"\"

Respond with ONLY a number on the scale; do not explain.
```

`scale_explanation`:
- `"0-1"` → `"0 means the output fails the criterion completely. 1 means it fully satisfies the criterion."`
- `"1-5"` → `"1 is worst; 5 is best."`

**Response parsing** uses a strict regex (`r"-?\d+(?:\.\d+)?"`) over
the LLM's text response. Multiple numbers → take the first. No numeric
match → `MetricsRuntimeError("llm_judge could not parse a number from
<truncated response>")` BUBBLES (not silently 0.0) — the user wants to
see this in their eval output.

`"1-5"` results are rescaled via `(value - 1) / 4`, clamped to
`[0, 1]`. `"0-1"` values are clamped without rescaling.

The judge call uses `temperature=0.0`, `max_tokens=50` — short
numeric responses only; no chain-of-thought.

### Error hierarchy

```python
class MetricsError(Exception):
    """Base for built-in metric helper errors."""

class MetricsConfigError(MetricsError):
    """Caller-side misconfiguration (bad args at call time)."""

class MetricsRuntimeError(MetricsError):
    """Helper failed at runtime (e.g. llm_judge response parse failure)."""
```

Helpers that need an LLM use `LLMProviderError` from AJ-18 verbatim;
the wrapping is `MetricsRuntimeError` only when the failure is in the
helper's own logic (parsing, validation), not the underlying provider.

## Cross-cuts

### AJ-4 (`EvalOutput`) — additive
- New field `tool_calls: tuple[str, ...]` on `EvalOutput`.
- Default value `()` for cases where capture is unavailable (workflow
  targets, custom datasets, etc.).
- The field is documented in the spec for AJ-4 via implementation
  notes (no changes to the spec file itself — fields are additive).

### AJ-4 (`EvalRunner`) — additive
- The runner passes a new `tool_calls_sink: list[str] | None`
  parameter into `AgentRuntime.run(...)` alongside the existing
  `cost_sink=`. Captures every successful tool dispatch's name during
  the case. The runner reads the populated list and stamps the new
  `EvalOutput.tool_calls` tuple.
- Workflow targets: no `tool_calls_sink` plumbing in v0.1; the field
  defaults to `()`.

### AJ-1 (`AgentRuntime`) — additive
- New optional kwarg `tool_calls_sink: list[str] | None = None` on
  `AgentRuntime.run(...)` and `.stream(...)`. When non-None, every
  successfully-executed tool's `name` is appended in dispatch order.
  Failed tool calls (validation error, tool exception) are NOT
  appended — `tool_called` semantically asks "did the agent USE the
  tool".
- Documented as private orchestrator API (same disclaimer as
  `cost_sink`).
- Backwards-compatible: default `None` keeps existing behaviour.

### AJ-4 (storage) — additive
- `EvalRun` JSON schema gains `tool_calls: list[str]` under each
  `cases[i].output` entry.
- Schema version stays at `1` — the new field is OPTIONAL on load
  (`load_eval_run` reads `tool_calls` if present, defaults to `()`
  otherwise). Old run files load cleanly with `tool_calls=()`.
  Documented in `storage.py` with a migration comment.

### AJ-4 (observability) — no changes
- `EvalOutput.tool_calls` is a runner-captured list, not an OTel
  attribute. The underlying `execute_tool {name}` spans (AJ-28)
  already carry that info on the trace tree; this field is just a
  convenience cache for metric helpers.

## Design rules

- **Helpers are functions, not decorators**. The user wraps them in
  their own `@Metric` body.
- **Every helper returns `float` in `[0.0, 1.0]`**. Clamping happens
  inside the helper, not in callers.
- **Sync where possible, async only where required**. `llm_judge` is
  async because it does network I/O; everything else is sync to keep
  `@Metric` methods simple.
- **Caller-side errors are typed and explicit**. Wrong args →
  `MetricsConfigError`. Helper-internal failures →
  `MetricsRuntimeError`. Provider failures bubble as `LLMProviderError`.
- **No global state**. The `llm_judge` cache lives per `_judge_cache`
  instance created per call invocation when `cache=True`. For
  cross-call caching the user creates a shared `JudgeCache` instance
  and passes it (escape hatch, see below).

### Escape hatch: shared `JudgeCache`

```python
from ajolopy.eval.metrics import JudgeCache, llm_judge

cache = JudgeCache()

@Metric
async def helpful(self, output, expected) -> float:
    return await llm_judge(
        output, criterion="...", model="...",
        cache=cache,
    )
```

`cache` accepts `bool` (the default-`False` shorthand) OR a `JudgeCache`
instance. When given an instance, repeated calls across `@Metric`
methods (even across different `@Eval` suites) share the cache. The
instance is mutable; the user can clear it (`cache.clear()`).

## Out of scope for this item

- **Disk-backed `llm_judge` cache** → v0.2. v0.1 is in-memory only.
- **`partial=True` for `json_match`** → v0.2.
- **LLM-based `intent_match`** → v0.2. v0.1 ships heuristic only;
  users who need LLM-classified intents wrap `llm_judge` themselves.
- **Workflow-target `tool_calls` capture** → AJ-31 / future workflow
  pass.
- **Multi-language tokenisation for `intent_match`** → v0.2 (currently
  pure substring).
- **`tool_called` with argument inspection** ("did the agent call
  `lookup_order(id='123')` specifically?") → v0.2. v0.1 only checks
  by name.
- **OTel-trace-driven metrics** (read span attributes inside the
  metric body) → not in v0.1. Helpers operate on `EvalOutput` only.

## Acceptance criteria

Each item must have at least one passing test. **`llm_judge` tests use
a `FakeLLMProvider`** (or a similar test double for `LLMProvider`); no
real LLM calls in CI. `AgentRuntime.tool_calls_sink` tests reuse the
existing `tests/agent/test_runtime_cost_sink.py` pattern.

### `EvalOutput.tool_calls` cross-cut

- [x] `EvalOutput` has a new `tool_calls: tuple[str, ...]` field with
      a tuple default. Existing call sites that build `EvalOutput`
      without the new field continue to work via dataclass default.
- [x] `EvalRun` JSON round-trips `tool_calls` (test_storage extension).
- [x] Loading a run file written WITHOUT `tool_calls` (old schema)
      yields `tool_calls=()` and no error — verified with a fixture.
- [x] `AgentRuntime.run(cost_sink=..., tool_calls_sink=[])`
      populates the sink with every dispatched tool's name in call
      order; sync + async tool methods both contribute.
- [x] Failed tool dispatch (validation error, tool method raise) does
      NOT append to `tool_calls_sink` — only successful invocations.
- [x] `EvalRunner` passes a fresh `tool_calls_sink=[]` per case and
      stamps the captured tuple onto `EvalOutput.tool_calls`.
- [x] Workflow-target cases yield `EvalOutput.tool_calls == ()`
      (v0.1 limitation documented in spec).

### `exact_match`

- [x] `exact_match("hello", "hello") == 1.0`.
- [x] `exact_match("hello", "world") == 0.0`.
- [x] `exact_match("  hello  ", "hello") == 1.0` (whitespace stripped
      both sides).
- [x] `exact_match("Hello", "hello") == 0.0` (case-sensitive default).
- [x] `exact_match("Hello", "hello", case_insensitive=True) == 1.0`.
- [x] `exact_match(EvalOutput(text="hello", ...), "hello") == 1.0`
      (EvalOutput input accepted).
- [x] `exact_match("42", 42) == 1.0` (expected coerced via `str`).

### `json_match`

- [x] `json_match('{"a": 1}', {"a": 1}) == 1.0`.
- [x] `json_match('{"a": 1}', {"a": 2}) == 0.0`.
- [x] `json_match('[1, 2, 3]', [1, 2, 3]) == 1.0` (arrays).
- [x] `json_match('not json', {"a": 1}) == 0.0` (parse failure →
      mismatch, NOT raise).
- [x] `json_match(EvalOutput(text='{"a": 1}', ...), {"a": 1}) == 1.0`.
- [x] `json_match('{"a": 1}', {"a": 1}, partial=True)` raises
      `MetricsConfigError` ("partial=True is reserved for v0.2").

### `contains` / `not_contains`

- [x] `contains("hello world", "hello") == 1.0`.
- [x] `contains("hello world", "missing") == 0.0`.
- [x] `contains("Hello World", "hello") == 1.0` (case-insensitive
      default).
- [x] `contains("Hello World", "hello", case_sensitive=True) == 0.0`.
- [x] `contains("a b c", ["x", "b"], mode="any") == 1.0`.
- [x] `contains("a b c", ["x", "y"], mode="any") == 0.0`.
- [x] `contains("a b c", ["a", "b"], mode="all") == 1.0`.
- [x] `contains("a b c", ["a", "x"], mode="all") == 0.0`.
- [x] `contains("text", []) ` raises `MetricsConfigError`.
- [x] `not_contains("hello", "world") == 1.0`.
- [x] `not_contains("hello world", "hello") == 0.0`.
- [x] `not_contains("text", ["api_key", "password"]) == 1.0`.
- [x] `not_contains` accepts an `EvalOutput` input.

### `intent_match`

- [x] `intent_match(EvalOutput(text="this is an order_status check"),
      "order_status") == 1.0`.
- [x] `intent_match(EvalOutput(text="hello"), "order_status") == 0.0`.
- [x] Case-insensitive by default.
- [x] List intent: any-of match.
- [x] `mode="exact"`: `intent_match(EvalOutput(text="ORDER_STATUS"),
      "order_status", mode="exact") == 1.0`.

### `tool_called`

- [x] `tool_called(EvalOutput(..., tool_calls=("lookup_order",)),
      "lookup_order") == 1.0`.
- [x] `tool_called(EvalOutput(..., tool_calls=("other",)),
      "lookup_order") == 0.0`.
- [x] `tool_called(EvalOutput(..., tool_calls=()), None) == 1.0` (no
      tool was the expectation).
- [x] `tool_called(EvalOutput(..., tool_calls=("any",)), None) == 0.0`
      (a tool was called but expected NONE).
- [x] `tool_called(EvalOutput(..., tool_calls=("a", "b")),
      ["a", "b"], mode="all") == 1.0`.
- [x] `tool_called(EvalOutput(..., tool_calls=("a",)), ["a", "b"],
      mode="all") == 0.0`.
- [x] `tool_called("plain string", "lookup_order")` raises
      `MetricsConfigError`.

### `llm_judge`

- [x] With a `FakeLLMProvider` returning `"0.85"`, `llm_judge(...)`
      returns `0.85`.
- [x] With a `FakeLLMProvider` returning `"   The score is 4 out of
      5."` and `scale="1-5"`, returns `0.75` (rescaled from 4 via
      `(4-1)/4`).
- [x] Out-of-range `"0-1"` response is clamped: `"1.5"` → `1.0`,
      `"-0.5"` → `0.0`.
- [x] No numeric content in response → `MetricsRuntimeError`.
- [x] `expected=None` omits the "ideal response" block from the
      prompt (verified by capturing the constructed prompt and
      asserting no "Expected" substring).
- [x] `expected="ideal"` includes the block.
- [x] `cache=True` makes a second call with identical args return
      from cache without invoking the provider (verified with a
      `call_count` on the fake).
- [x] `cache=False` (default) calls the provider every time.
- [x] Shared `JudgeCache` instance survives across `llm_judge` calls
      in the same process.
- [x] `JudgeCache.clear()` empties the cache.
- [x] An `LLMProviderError` from the provider bubbles UP, not wrapped.
- [x] An `EvalOutput` input is reduced to its `.text` field for the
      judge prompt.
- [x] Plain `str` input is used verbatim.
- [x] Cache key includes `model` — different models with same inputs
      do NOT collide.

### Composition with `@Eval` (smoke test)

- [x] An `@Eval` class with `@Metric` methods using each of the seven
      helpers runs end-to-end via `EvalRunner` against a mocked agent
      target. Aggregate score is computed correctly.
- [x] `tool_called` reads from the captured `tool_calls_sink`
      correctly when the mocked agent dispatches tools.

### Public re-exports

- [x] `from ajolopy.eval.metrics import (exact_match, json_match,
      contains, not_contains, intent_match, tool_called, llm_judge,
      JudgeCache, MetricsError, MetricsConfigError,
      MetricsRuntimeError)` works.
- [x] `ajolopy.eval.metrics.__all__` lists exactly those names.
- [x] No top-level `ajolopy` re-export added — these are helper
      functions, not primitives.

## Implementation pointers

- Source: `src/ajolopy/eval/metrics/` (new sub-package — promote the
  existing `metric.py` file to a sub-package directory).
  - `__init__.py` — public re-exports.
  - `errors.py` — `MetricsError`, `MetricsConfigError`,
    `MetricsRuntimeError`.
  - `text.py` — `exact_match`, `contains`, `not_contains`,
    `intent_match`. Pure-text helpers grouped together.
  - `structured.py` — `json_match`. JSON shape helpers (room for v0.2
    extensions like `jsonpath_match`).
  - `tools.py` — `tool_called`. Reads `EvalOutput.tool_calls`.
  - `judge.py` — `llm_judge` + `JudgeCache`. The async + provider +
    cache work concentrates here so the file-by-file picture stays
    tidy.
  - `_resolve.py` — internal helper that coerces `output: EvalOutput |
    str` → `text: str` and validates types per helper. Shared so the
    coercion rule is documented in one place.

  **Note**: there is currently a `src/ajolopy/eval/metric.py` file
  housing the `@Metric` decorator (AJ-4). The new metrics-helpers
  sub-package is `src/ajolopy/eval/metrics/` (plural directory) —
  distinct from `metric.py` (singular file). AJ-26 does NOT rename
  the decorator's home.
- Cross-cut to `src/ajolopy/eval/results.py`:
  - Add `tool_calls: tuple[str, ...] = ()` field on `EvalOutput`.
  - Field default keeps existing call sites working.
- Cross-cut to `src/ajolopy/eval/runner.py`:
  - Allocate a per-case `tool_calls_sink: list[str] = []`. Pass to
    `target_instance.run(cost_sink=..., tool_calls_sink=...)`.
  - On case completion, stamp `tuple(sink)` onto `EvalOutput.tool_calls`.
  - Workflow targets: skip the sink kwarg (the workflow's `.run`
    signature does not accept it in v0.1); `tool_calls` defaults to `()`.
- Cross-cut to `src/ajolopy/agent/runtime.py`:
  - Add `tool_calls_sink: list[str] | None = None` kwarg on
    `AgentRuntime.run` AND `AgentRuntime.stream`.
  - When non-None, append each successful tool dispatch's `name`
    inside `_execute_single_tool` (or wherever the tool name resolves
    to a real call — NOT on validation failure or tool exception).
- Cross-cut to `src/ajolopy/eval/storage.py`:
  - `save_eval_run` serialises `tool_calls` as a JSON list inside
    each case's `output` object.
  - `load_eval_run` reads it back; missing field on old run files
    yields `tool_calls=()` with no error. Comment the migration
    behaviour in-place.
- Reused without modification:
  - `LLMProvider`, `resolve_provider`, `get_provider_class`,
    `Message`, `Response`, `LLMProviderError` from
    `ajolopy.providers`.
  - `EvalOutput` data class shape; we add a field, no other change.
- Tests: `tests/eval/metrics/` (new sub-directory).
  - `test_exact_match.py`
  - `test_json_match.py`
  - `test_contains.py`
  - `test_not_contains.py`
  - `test_intent_match.py`
  - `test_tool_called.py`
  - `test_llm_judge.py`
  - `test_judge_cache.py`
  - `test_composition.py` — wires the helpers into a fake `@Eval`
    suite and asserts the aggregate score.
  - `test_public_api.py`
  - Plus extensions to `tests/agent/test_runtime_cost_sink.py` (or a
    new sibling) covering `tool_calls_sink`.
  - Plus extensions to `tests/eval/test_storage.py` covering the new
    `tool_calls` JSON field + back-compat load.
- Runtime deps: none new (stdlib `json`, `hashlib`, `re`).

## Implementation notes

### Layout shipped

```
src/ajolopy/eval/metrics/
  __init__.py        # public re-exports
  errors.py          # MetricsError / MetricsConfigError / MetricsRuntimeError
  _resolve.py        # coerce_to_text + require_eval_output (shared internals)
  text.py            # exact_match, contains, not_contains, intent_match
  structured.py      # json_match
  tools.py           # tool_called
  judge.py           # llm_judge + JudgeCache + module-level _DEFAULT_JUDGE_CACHE
```

### Cross-cut delta

- `EvalOutput` gained `tool_calls: tuple[str, ...] = ()`. The default
  value keeps every pre-existing call site working; the field is
  populated by the runner for agent targets and stays `()` for
  workflow targets and any callers that build the dataclass manually.
- `AgentRuntime.run(...)` and `.stream(...)` gained a private
  `tool_calls_sink: list[str] | None = None` kwarg mirroring
  `cost_sink`. The orchestrator hook appends each
  SUCCESSFULLY-dispatched tool's name in call order; validation
  errors and tool exceptions DO NOT append. Implementation lives in
  `_execute_tool_calls` (post-gather inspection of `Message.is_error`)
  so both sync and async tool methods route through one append site.
- `EvalRunner` allocates a fresh `tool_calls_sink=[]` per agent-target
  case and passes it to `AgentRuntime.run(...)` alongside the existing
  `cost_sink`. Workflow targets skip the kwarg entirely (the
  decorator-injected `run` does not accept it in v0.1).
- `save_eval_run` serialises `tool_calls` as a JSON list under each
  case's `output` block. `load_eval_run` reads it back as a tuple,
  defaulting to `()` when the field is absent (old run files from
  pre-AJ-26 load cleanly). Schema version stays at `1`.

### `llm_judge` details

- `cache=True` shares a single module-level `_DEFAULT_JUDGE_CACHE`
  across every call in the process. For isolation, callers pass a
  fresh `JudgeCache()` instance (escape hatch — documented in the
  Brief).
- Cache key: sha256 of NUL-joined
  `(criterion, output_text, expected_text_or_empty, model, scale)`.
  NUL is reserved as the join byte so distinct `(a, b)` pairs cannot
  collide with one `(a + delimiter + b)` value.
- Response parsing: first `r"-?\d+(?:\.\d+)?"` match. No match raises
  `MetricsRuntimeError` (NOT silent 0.0). `scale="1-5"` rescales via
  `(value - 1) / 4`, then clamps. `scale="0-1"` clamps without
  rescaling.
- `temperature=0.0`, `max_tokens=50`, `tools=None`, `cache=False` on
  every provider call — short numeric responses only.

### Testing seam

- `tests/eval/metrics/test_llm_judge.py` defines a `FakeLLMProvider`
  whose `complete` returns scripted strings and records `call_count`
  / `last_prompt` / `last_kwargs`. Every `llm_judge` test passes the
  fake via the `provider=` kwarg — no registry roundtrip, no network.
- `tests/agent/test_runtime_tool_calls_sink.py` mirrors the
  pre-existing `cost_sink` test file, covering successful dispatch,
  validation-error rejection, tool-exception rejection, multiple-call
  ordering, async-tool dispatch, and unknown-name rejection.
