# AJ-35 — `ajolopy eval` CLI runner

> Tracked in [`board.json`](../board.json) as `AJ-35`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth: Brief v4.0 §"dolor #3" + `09 - Eval framework` +
> `06 - CLI completa` §`ajolopy eval`. If this file ever conflicts with
> the Brief, the Brief wins.
>
> This item BUNDLES AJ-27 (`ajolopy eval --compare-with regression
> detection`) since the flag is one of the four AJ-35 ship-items per
> the board title. AJ-27 is cancelled by the chore commit in this PR.

## What

`ajolopy eval [TARGET ...]` is a new CLI subcommand that:

1. **Discovers** `@Eval`-decorated classes by importing the supplied
   `TARGET` arguments (each `package.module` or
   `package.module:ClassName`). Default when no `TARGET` is supplied:
   the `evals` package at the cwd.
2. **Filters** the discovered suite set with `--filter <pattern>`
   (fnmatch, case-insensitive).
3. **Runs** each suite via the existing `EvalRunner` (AJ-4).
4. **Persists** every produced `EvalRun` to
   `.ajolopy/eval-runs/<timestamp>-<SuiteName>.json` (always — opens
   the door to `--compare-with` without extra flags).
5. **Compares** against a prior run set when `--compare-with <run-id>`
   is supplied. Highlights newly-failing cases per suite. Sets the
   process exit code to non-zero when a regression is detected.
6. **Reports** in two modes:
   - Default: rich emoji-coloured output (TTY) or plain text
     (non-TTY).
   - `--ci`: JSON snapshot on stdout matching the Brief literal,
     non-zero exit if any suite failed.
7. **Dry-run** estimates cost via the AJ-30 pricing catalog before
   actually running anything. Prompts for confirmation unless the
   user uses `--ci`.

## Why

Brief v4.0 dolor #3 — "modelo nuevo + evals que no tenías bajan en
silencio" — points directly at this command. The wedge user (AI
Engineer at a Series A startup) wires it into CI; the regression
catches happen automatically. Without the CLI, AJ-4's `EvalRunner` is
programmatic-only — usable from tests but not from the PR-blocking
hook the Brief promises.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: `ajolopy eval` finds `evals/`, runs every
  `@Eval` suite in it, prints emoji-coloured results, saves
  snapshots. Zero flags for the common case.
- **Escape hatch**: every flag is opt-in; the underlying `EvalRunner`
  is the programmatic alternative for users who want to script their
  own runner with custom filtering / aggregation.

## Public surface (v0.1)

```bash
ajolopy eval [TARGET ...] [OPTIONS]
```

### Positional arguments

- `TARGET` (zero or more) — `package.module` (walks the module's
  `__dict__` for `@Eval` classes; if it's a package, recursively walks
  every submodule) OR `package.module:ClassName` (single class).
- Default when zero `TARGET` arguments: `evals` (the `evals` package
  at `os.getcwd()`).

### Flags (in declaration order)

```text
--filter <pattern>           fnmatch over suite class names, case-insensitive
--ci                         JSON output to stdout; suppresses --dry-run prompt
--compare-with <run-id>      regression detection against a prior run set
--threshold-override <N>     force per-suite threshold to N (in [0.0, 1.0])
--dry-run                    estimate cost; prompt y/N before running
--save-dir <path>            override the default .ajolopy/eval-runs/
--no-save                    skip persistence for this invocation
-h, --help                   usage
```

### `--compare-with` `<run-id>` shapes

The CLI accepts THREE forms for `<run-id>`:

| Form              | Meaning                                                                                              |
|-------------------|------------------------------------------------------------------------------------------------------|
| `last`            | For each suite, picks the MOST RECENT run file under the save dir whose suffix matches the suite name AND whose timestamp predates this invocation. |
| `YYYY-MM-DDTHH-MM-SSZ` | Picks every run file with that timestamp prefix in the save dir (one per suite). |
| `<path>`          | A directory containing one or more `*-<SuiteName>.json` files. (Useful for fetched-artifact comparisons in CI.) |

If no matching prior run is found for a suite, that suite is run
normally but `--compare-with` produces no delta for it (a `NEW` badge
in default output / `compared_with: null` in `--ci` JSON).

### Discovery semantics

`TARGET` resolution:

1. If `TARGET` contains a `:`, treat as `module:ClassName`:
   - Import the module via `importlib.import_module`.
   - Look up `getattr(module, "ClassName")`.
   - Verify the class carries `_ajolopy_eval` metadata; else exit 1
     with a usage hint.
2. Else `TARGET` is a module/package path. Import the module. If the
   module is a package (has `__path__`), recursively walk every
   submodule via `pkgutil.walk_packages`. For each module visited,
   inspect its `__dict__` for classes carrying `_ajolopy_eval`.
3. Dedupe across `TARGET` arguments (a class found twice via two
   targets is run once).

Import failures (`ModuleNotFoundError`, `ImportError`) → exit code 1
with the offending target and reason.

### Filter semantics

`--filter` accepts an fnmatch pattern (lowercased). The CLI lowercases
each suite class's `__name__` and matches against the pattern. The
filter applies AFTER discovery; an empty filter set after filtering
exits with code 1 and a hint.

### Run + persist

For each discovered (and filtered) suite, in declaration order
(stable ordering: module attribute order):

1. Build a shared `EvalRunner(eval_runs_dir=<save dir or default>)`.
2. Build a single shared timestamp string for this invocation:
   `datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")`.
3. For each suite:
   - If `--threshold-override` is set, monkey-patch the suite's
     `_ajolopy_eval` threshold for this invocation (do NOT persist
     the override into the metadata; restore after the run).
   - Await `runner.run(suite_cls)` → `EvalRun`.
   - If `--no-save` is NOT set: save to
     `<save_dir>/<timestamp>-<SuiteName>.json`.
   - Compare with the resolved prior run for this suite (if any).
4. Render per-mode output (default vs `--ci`).
5. Compute exit code (see "Exit codes" below).

Suites run **sequentially** in v0.1 — each suite uses its own
`@Eval(concurrency=N)` for case-level parallelism. Parallel suites
multiply concurrency in unpredictable ways and complicate cost
tracking; defer to v0.2.

### Default output

```text
$ ajolopy eval

📊 Running 4 eval suites...

✅ CustomerSupportEval  → score: 0.91 (threshold: 0.85)  [12 cases]
✅ TriageEval           → score: 0.88 (threshold: 0.85)  [50 cases]
⚠️  BillingEval         → score: 0.83 (threshold: 0.85)  [25 cases]  REGRESSION
✅ TechnicalEval        → score: 0.94 (threshold: 0.85)  [30 cases]

Summary: 3 passed, 1 failed
BillingEval failed: helpful=0.78 (was 0.92 in last run)

Exit code: 1
```

- `📊 Running N eval suites...` header.
- Per-suite row: status icon + name + score + threshold + case count
  + optional `REGRESSION` badge + optional `NEW` badge.
- Status icons:
  - `✅` — `passed=True` and (no compare OR no regression).
  - `⚠️ ` — `passed=True` BUT regression detected against compare.
  - `❌` — `passed=False`.
- Summary line: `Summary: <passed> passed, <failed> failed[, <regressions> regression(s)]`.
- One regression-detail line per regressed metric (only when
  `--compare-with` produced a delta and the metric regressed).
- Final `Exit code: <N>` line.
- ANSI colors via stdlib (`os.isatty` + manual ANSI). NO `rich`
  dependency. Auto-disable when stdout is not a TTY.

### `--ci` output (JSON, stdout)

Match the Brief literal §"Output JSON-friendly en modo `--ci`":

```json
{
  "schema_version": 1,
  "timestamp": "2026-05-14T22:30:00Z",
  "suites": [
    {
      "name": "SupportEval",
      "cases": 50,
      "metrics": {
        "helpful": {"aggregator": "mean", "aggregate": 0.91, "passed": true},
        "safe": {"aggregator": "min", "aggregate": 1.00, "passed": true}
      },
      "aggregate_score": 0.92,
      "threshold": 0.85,
      "passed": true,
      "compared_with": "2026-05-14T22-29-00Z-SupportEval.json",
      "regressions": []
    }
  ],
  "passed": 3,
  "failed": 1,
  "regressions": 0,
  "exit_code": 1
}
```

- `compared_with` is `null` when no prior run is available.
- `regressions` (per-suite) is the list of regressed metric names
  (sorted ascending). Empty when no comparison was made or no
  regression detected.
- Top-level `regressions` is the total count.

### `--dry-run`

```text
$ ajolopy eval --dry-run

SupportEval (50 cases)
  Agent calls:  50  (~$0.42 estimated)
  LLM judges:  100  (~$0.28 estimated)
  Total estimated cost: ~$0.70

BillingEval (25 cases) — model gpt-4o-mini not in pricing catalog
  Estimated cost: unknown

Total: ~$0.70 (1 suite estimated, 1 unknown)

Proceed? (y/N)
```

- Per-suite estimate: `cases × (input_token_estimate × input_rate +
  output_token_estimate × output_rate)` for the agent model. Token
  estimates baked in: `INPUT_TOKEN_ESTIMATE = 500`, `OUTPUT_TOKEN_ESTIMATE = 300`.
- LLM-judge estimate (when the suite is detected to use `llm_judge`
  — heuristic: ANY `@Metric` is `async`): assume one judge call per
  case at `JUDGE_INPUT = 600` / `JUDGE_OUTPUT = 50` tokens with the
  agent's same model rate. (Crude but documented; AJ-26's
  `llm_judge` takes its own model so the real cost varies. v0.2 can
  refine.)
- Unknown model (not in AJ-30 pricing catalog) → "unknown" line,
  contributes 0 to the total.
- Prompt: `Proceed? (y/N)` — case-insensitive `y` / `Y` continues;
  anything else aborts (exit 0, no run). `--ci` SKIPS the prompt
  entirely (it's not interactive); use `--dry-run --ci` to JUST
  print the estimate and exit 0 without running.

### Exit codes

| Code | Meaning                                                         |
|------|-----------------------------------------------------------------|
| 0    | All suites passed AND no regression detected.                   |
| 1    | At least one suite failed OR a regression was detected.         |
| 2    | Usage error (argparse `SystemExit`).                            |
| 3    | Discovery / import error (target not found, no `@Eval` classes). |
| 4    | `--dry-run` user declined the prompt. Distinct from 0 so scripts can detect. |

## Cross-cuts

### AJ-4 (`EvalRun.save` filename) — additive
- `EvalRun.save(path)` already accepts an optional path. The CLI
  passes `<save_dir>/<timestamp>-<SuiteName>.json` explicitly. No
  signature change.
- Default path (when `save(None)`) stays
  `<DEFAULT_EVAL_RUNS_DIR>/<timestamp>.json` (no suite suffix) — used
  only by programmatic callers; the CLI always supplies its own
  path.

### AJ-60 (CLI dispatcher) — additive
- New subcommand `eval` registered via the existing
  `src/ajolopy/cli/commands/__init__.py::register_subcommands`
  registry. No changes to the dispatcher itself.

### AJ-30 (pricing catalog) — reuse
- `--dry-run` reads the active catalog via `get_active_catalog()` and
  resolves per-model rates. Missing model → "unknown" line.

### Board
- AJ-27 (`ajolopy eval --compare-with regression detection`) marked
  `cancelled` in the chore commit — its surface is delivered here.

## Design rules

- **No new runtime deps**. Discovery via `importlib` + `pkgutil`.
  Colors via stdlib + `os.isatty`. JSON output via stdlib `json`.
- **Deterministic ordering**. Discovered suites are ordered by
  (target index, module name, class declaration order). Run JSON
  reflects that order so diffs are stable.
- **No hidden side-effects**. The CLI never modifies project files
  outside `<save_dir>`. Suite metadata `--threshold-override` is
  monkey-patched only for the duration of `runner.run()` (restored
  via `try/finally`).
- **`--ci` is non-interactive**. When `--ci` is set, the prompt for
  `--dry-run` is skipped; stdout is JSON only; warnings / errors go
  to stderr.

## Out of scope for this item

- **Parallel suite execution** — sequential in v0.1; case-level
  parallelism via `@Eval(concurrency=N)` still applies.
- **Retention policy for `.ajolopy/eval-runs/`** — no auto-cleanup
  in v0.1; users prune manually.
- **`--watch` mode** (re-run on file change) — v0.2.
- **`--json-out <path>` flag** (write `--ci` JSON to a file instead
  of stdout) — v0.2.
- **HTML / per-suite report generation** — v0.2.
- **Eval-level dry-run accuracy** (real token counting via
  tokeniser) — v0.2; v0.1 uses the documented token estimates.
- **`--save-on-cancel`** (persist partial runs after a Ctrl+C) —
  v0.2.

## Acceptance criteria

Each item must have at least one passing test. **Mock targets** at
the `EvalRunner.run` boundary OR via small fake `@Eval` classes —
the CLI tests do NOT exercise real agent runtimes.

### Discovery

- [x] `ajolopy eval` with no targets defaults to importing `evals`.
- [x] `ajolopy eval pkg.mod` imports `pkg.mod`, discovers `@Eval`
      classes in its `__dict__`.
- [x] `ajolopy eval pkg.mod:Cls` resolves to the named class.
- [x] `ajolopy eval pkg.mod:NotAnEval` exits 1 with "not an @Eval
      class" message.
- [x] `ajolopy eval pkg` walks every submodule recursively.
- [x] Two targets producing the same class dedupe (the class runs
      once).
- [x] `ajolopy eval pkg.nonexistent` exits 1 with the module path
      in the message.
- [x] Discovery preserves declaration order across targets and
      modules.
- [x] Zero `@Eval` classes after discovery exits 3 with "no eval
      suites discovered" hint.

### Filtering

- [x] `--filter "Support*"` keeps only suites whose lowercased name
      starts with "support".
- [x] Filter is case-insensitive.
- [x] An empty match set exits 1 with "no suites matched filter".

### Run + persist

- [x] Each suite produces an `EvalRun` written to
      `<save_dir>/<timestamp>-<SuiteName>.json`.
- [x] All suites in one invocation share the same timestamp prefix.
- [x] `--no-save` skips writes entirely (no files created).
- [x] `--save-dir /tmp/x` writes to that path.
- [x] `--threshold-override 0.9` is applied to every suite for the
      invocation; original `_ajolopy_eval.threshold` is restored
      after.
- [x] `--threshold-override` outside `[0, 1]` exits 2 (argparse
      usage error).
- [x] Suites run in declaration order; the CLI does NOT parallelise.

### Default output

- [x] TTY stdout: rendered with ANSI colors + `✅` / `⚠️ ` / `❌`
      glyphs.
- [x] Non-TTY stdout: no ANSI codes; ASCII status badges
      (`[PASS]` / `[WARN]` / `[FAIL]`).
- [x] Per-suite line includes name, score (3 decimals), threshold
      (3 decimals), and case count.
- [x] `⚠️ ` only fires when `--compare-with` produced a regression
      (`passed=True` AND `regressions != []`).
- [x] Summary line counts.
- [x] Final `Exit code: <N>` line matches the actual exit code.

### `--ci` output

- [x] `--ci` writes JSON to stdout matching the documented schema.
- [x] `schema_version` field is `1`.
- [x] `compared_with` is `null` when no prior run is available
      for a suite.
- [x] `passed` (top-level) is the count of passing suites; same for
      `failed`.
- [x] `regressions` (top-level) is the total number of regressed
      metrics across all suites.
- [x] `exit_code` field matches the process exit code.

### `--compare-with`

- [x] `--compare-with last` picks the most-recent prior run file
      per suite (timestamp before this invocation's timestamp).
- [x] `--compare-with 2026-05-14T22-00-00Z` picks files with that
      exact timestamp prefix.
- [x] `--compare-with /path/to/dir` reads runs from the given
      directory.
- [x] A suite with NO prior run gets `compared_with=null` in
      `--ci` JSON and a `NEW` badge in default output.
- [x] A regression on at least one suite forces exit code 1 even
      when every suite individually has `passed=True`.
- [x] Regression line in default output names the regressed metric
      (e.g., `helpful=0.78 (was 0.92 in last run)`).
- [x] `EvalComparisonError` (dataset sha256 mismatch, suite name
      mismatch) surfaces as a per-suite warning to stderr; the
      suite is still run / saved, just NOT compared.

### `--dry-run`

- [x] `--dry-run` prints the cost estimate table and prompts.
- [x] User typing `y` proceeds with the full run.
- [x] User typing `n` (or anything not in `y/Y`) exits 4 without
      running.
- [x] `--dry-run --ci` prints the estimate as JSON (top-level
      `dry_run: true`) and exits 0 without prompting OR running.
- [x] Unknown model produces an "unknown" line; the total counts
      the known-model estimates only.

### Exit codes

- [x] All-passing run, no compare → exit 0.
- [x] Any suite failed → exit 1.
- [x] All passed but a regression detected → exit 1.
- [x] Bad argparse args (e.g. `--threshold-override 1.5`) → exit 2.
- [x] Discovery import error / zero suites → exit 3.
- [x] `--dry-run` user declined → exit 4.

### Public re-exports

- [x] `ajolopy eval --help` lists every documented flag in the
      help text.
- [x] The subcommand is registered via
      `src/ajolopy/cli/commands/__init__.py` (the existing
      registry seam).
- [x] No top-level Python re-exports added — the CLI is the
      surface; the underlying `EvalRunner` already lives in
      `ajolopy.eval`.

## Implementation pointers

- Source: `src/ajolopy/cli/commands/eval.py` (new).
  - `register(subparsers)` is the public entry — called by
    `cli/commands/__init__.py::register_subcommands`.
  - `_command(args, *, stdout, stderr) -> int` is the orchestrator.
    Test seam: pass StringIO buffers from tests, get the exit code
    + captured text back without touching real stdout.
  - `_discover(targets) -> list[type]` — argparse-side resolution.
  - `_filter_suites(suites, pattern)` — fnmatch helper.
  - `_run_suites(suites, *, runner, ...) -> list[EvalRun]` — wraps
    each suite with `--threshold-override` monkey-patch in a
    try/finally.
  - `_resolve_compare(run_id, save_dir, suite_name, current_timestamp) -> Path | None`
    — the three forms.
  - `_render_default(...)` and `_render_ci(...)` — output writers.
  - `_estimate_costs(suites) -> CostEstimate` — `--dry-run`.
- Cross-cut: `src/ajolopy/cli/commands/__init__.py` — add the
  `eval` entry to `register_subcommands`.
- Tests: `tests/cli/eval/` (new).
  - `test_discovery.py` — target resolution + dedupe.
  - `test_filter.py` — fnmatch + empty-match exit.
  - `test_run_and_persist.py` — save-dir, no-save, threshold-override.
  - `test_default_output.py` — emoji + plain + ANSI presence.
  - `test_ci_output.py` — JSON schema + exit code.
  - `test_compare_with.py` — three run-id forms + regression badge.
  - `test_dry_run.py` — prompt + decline + ci variant.
  - `test_exit_codes.py` — every documented code.
- Reused without modification:
  - `EvalRunner`, `EvalRun.save/load`, `compare_runs`,
    `EvalComparisonError` from `ajolopy.eval`.
  - `get_active_catalog` from `ajolopy.observability.pricing` for
    `--dry-run`.
  - `ajolopy.cli.commands` registry from AJ-60.
- Runtime deps: none new.

## Implementation notes

- **Threshold override via dynamic subclass.** `EvalMetadata` is a
  frozen dataclass; mutating it in place would break the AJ-4 contract
  and leak state to the next invocation. The CLI instead builds a
  transient subclass of the suite and shadows `_ajolopy_eval` with a
  `dataclasses.replace(metadata, threshold=N)` copy. The runner sees
  the override; the user's class stays untouched. See
  `_apply_threshold_override` in `src/ajolopy/cli/commands/eval.py`.
- **TTY detection.** `StringIO` raises
  `io.UnsupportedOperation` from `fileno()`, so a naive
  `os.isatty(stream.fileno())` blows up under the test harness. The
  CLI calls `stream.isatty()` when available and swallows the
  failure path, defaulting to "not a TTY" (ASCII badges, no ANSI).
- **NEW vs no-compare distinction.** The renderer needs to tell apart
  "no `--compare-with` was passed" from "compared but no prior run
  exists". The orchestrator threads a `compare_requested` flag
  through both renderers; the CI JSON sets `compared_with=null` only
  in the latter case, and the default renderer emits a `NEW` badge
  for it.
- **Discovery import boundary.** `pkgutil.walk_packages` walks
  sub-packages on demand; the CLI surfaces failures from any visited
  module via the same `_DiscoveryImportError` path so the user never
  has to dig through a partial trace.
- **Dry-run prompt threading.** `builtins.input` is the entry the
  CLI hits for the y/N prompt — tests monkeypatch it directly.
  `--dry-run --ci` skips the prompt entirely and emits a JSON
  estimate with `dry_run: true`; the run does not execute.
- **No new runtime deps.** Colours via stdlib + manual ANSI; JSON via
  stdlib; cost estimate via `get_active_catalog()` (AJ-30). The CLI
  ships zero new entries in `pyproject.toml`.
