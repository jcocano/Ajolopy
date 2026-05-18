"""``ajolopy eval [TARGET ...]`` subcommand.

The handler orchestrates four discrete phases:

1. **Discover** ``@Eval`` classes from the supplied ``TARGET`` arguments
   (``package.module`` or ``package.module:ClassName``). When no
   targets are supplied the CLI defaults to the ``evals`` package at
   the current working directory.
2. **Filter** the discovered set with ``--filter <pattern>`` (fnmatch,
   case-insensitive over the suite class names).
3. **Run** each suite through :class:`EvalRunner` and persist the
   resulting :class:`EvalRun` to
   ``<save-dir>/<timestamp>-<SuiteName>.json`` unless ``--no-save`` is
   set. ``--threshold-override <N>`` is applied via a dynamically
   constructed subclass so the user's :class:`EvalMetadata` is left
   untouched.
4. **Render** the per-suite + summary output, in either rich (default,
   TTY) or JSON (``--ci``) form, and surface the documented exit code.

The module deliberately avoids ``rich``: colours come from stdlib +
manual ANSI codes, gated on :func:`os.isatty`. Every IO call goes
through the injected ``stdout`` / ``stderr`` streams so the test seam
can drive the orchestrator with :class:`io.StringIO` buffers and
assert against the captured text + returned exit code.
"""

import argparse
import asyncio
import builtins
import dataclasses
import fnmatch
import importlib
import json
import pkgutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, cast

from ajolopy.eval import (
    EvalComparisonError,
    EvalRunner,
    compare_runs,
)
from ajolopy.eval.eval_decorator import EVAL_MARKER, EvalMetadata
from ajolopy.eval.storage import DEFAULT_EVAL_RUNS_DIR, load_eval_run
from ajolopy.observability.pricing import get_active_catalog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ajolopy.eval.results import EvalComparison, EvalRun


__all__ = [
    "EXIT_DISCOVERY",
    "EXIT_DRY_RUN_DECLINED",
    "EXIT_FAILED",
    "EXIT_OK",
    "EXIT_USAGE",
    "cmd_eval",
    "register",
]


# ---------------------------------------------------------------------------
# Exit-code constants (module-level so tests assert against names, not magic).
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_DISCOVERY = 3
EXIT_DRY_RUN_DECLINED = 4


# ---------------------------------------------------------------------------
# Cost-estimation constants for ``--dry-run``. Documented in the spec so
# tooling can audit the assumptions without spelunking the source.
# ---------------------------------------------------------------------------
INPUT_TOKEN_ESTIMATE = 500
OUTPUT_TOKEN_ESTIMATE = 300
JUDGE_INPUT_TOKEN_ESTIMATE = 600
JUDGE_OUTPUT_TOKEN_ESTIMATE = 50


# ---------------------------------------------------------------------------
# ANSI rendering — stdlib only.
# ---------------------------------------------------------------------------
_ANSI_RESET = "\x1b[0m"
_ANSI_BOLD = "\x1b[1m"
_ANSI_GREEN = "\x1b[32m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_RED = "\x1b[31m"


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``eval`` subparser to the dispatcher.

    ``_SubParsersAction`` is the documented type for argparse's
    subparser registry; the pyright ignore mirrors the convention used
    by every other ``ajolopy`` subcommand.
    """
    parser = sub.add_parser(
        "eval",
        help="Run @Eval suites discovered in the project.",
        description=(
            "Discover @Eval-decorated classes from one or more import targets, "
            "run them through the EvalRunner, persist each run, and optionally "
            "compare against a prior run set."
        ),
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help=(
            "Module(s) to import: 'pkg.mod' (discovers every @Eval in the "
            "module / walks submodules when it's a package) or "
            "'pkg.mod:ClassName' (single class). Defaults to 'evals'."
        ),
    )
    parser.add_argument(
        "--filter",
        dest="filter_pattern",
        default=None,
        metavar="PATTERN",
        help="fnmatch pattern over suite class names (case-insensitive).",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Emit JSON to stdout and skip the --dry-run prompt.",
    )
    parser.add_argument(
        "--compare-with",
        dest="compare_with",
        default=None,
        metavar="RUN_ID",
        help=(
            "Compare against a prior run set. Accepts 'last' (most recent "
            "matching file), an ISO timestamp prefix (e.g. "
            "'2026-05-14T22-00-00Z'), or a directory path holding prior "
            "run files."
        ),
    )
    parser.add_argument(
        "--threshold-override",
        dest="threshold_override",
        type=_threshold_arg,
        default=None,
        metavar="N",
        help="Override every suite's threshold for this invocation (in [0.0, 1.0]).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate cost and prompt before running (skipped under --ci).",
    )
    parser.add_argument(
        "--save-dir",
        dest="save_dir",
        default=None,
        metavar="PATH",
        help="Override the default .ajolopy/eval-runs/ persistence directory.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist runs to disk for this invocation.",
    )
    parser.set_defaults(func=cmd_eval)


# ---------------------------------------------------------------------------
# argparse type helpers
# ---------------------------------------------------------------------------


def _threshold_arg(value: str) -> float:
    """Argparse ``type=`` for ``--threshold-override`` with range check."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--threshold-override must be a number in [0.0, 1.0], got {value!r}."
        ) from exc
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError(
            f"--threshold-override must be in [0.0, 1.0], got {parsed}."
        )
    return parsed


# ---------------------------------------------------------------------------
# Entry point invoked by the dispatcher.
# ---------------------------------------------------------------------------


def cmd_eval(args: argparse.Namespace) -> int:
    """Dispatcher entry — adapts to the default ``stdout`` / ``stderr``."""
    return _command(args, stdout=sys.stdout, stderr=sys.stderr)


def _command(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
) -> int:
    """Orchestrate discovery → filter → (dry-run|run) → render → exit code."""
    targets: list[str] = list(cast("list[str]", args.targets)) or ["evals"]
    try:
        suites = _discover(targets)
    except _DiscoveryImportError as exc:
        print(f"ajolopy eval: {exc}", file=stderr)
        return EXIT_FAILED
    except _DiscoveryInvalidTargetError as exc:
        print(f"ajolopy eval: {exc}", file=stderr)
        return EXIT_FAILED

    if not suites:
        print(
            "ajolopy eval: no eval suites discovered. Decorate a class with "
            "@Eval(...) under the targeted module(s) or pass an explicit "
            "TARGET.",
            file=stderr,
        )
        return EXIT_DISCOVERY

    if args.filter_pattern is not None:
        filtered = _filter_suites(suites, cast("str", args.filter_pattern))
        if not filtered:
            print(
                f"ajolopy eval: no suites matched filter {args.filter_pattern!r}.",
                file=stderr,
            )
            return EXIT_FAILED
        suites = filtered

    save_dir = Path(cast("str", args.save_dir)) if args.save_dir is not None else None
    threshold_override = cast("float | None", args.threshold_override)

    if args.dry_run:
        decision = _handle_dry_run(
            suites,
            ci=bool(args.ci),
            stdout=stdout,
        )
        if decision != EXIT_OK:
            return decision
        if args.ci:
            # ``--dry-run --ci`` short-circuits: estimate is the
            # output, no run, exit 0.
            return EXIT_OK
        # Otherwise the user typed ``y`` and the run continues below.

    runner_dir = save_dir if save_dir is not None else DEFAULT_EVAL_RUNS_DIR
    runner = EvalRunner(eval_runs_dir=runner_dir)
    timestamp = _invocation_timestamp()

    runs = _run_suites(
        suites,
        runner=runner,
        timestamp=timestamp,
        save_dir=runner_dir,
        no_save=bool(args.no_save),
        threshold_override=threshold_override,
    )

    compare_requested = args.compare_with is not None
    comparisons: dict[str, EvalComparison | None] = {}
    if compare_requested:
        comparisons = _compare_runs(
            runs,
            compare_with=cast("str", args.compare_with),
            save_dir=runner_dir,
            current_timestamp=timestamp,
            stderr=stderr,
        )

    exit_code = _compute_exit_code(runs, comparisons)

    if args.ci:
        _render_ci(
            runs,
            comparisons=comparisons,
            compare_requested=compare_requested,
            timestamp=timestamp,
            exit_code=exit_code,
            stdout=stdout,
        )
    else:
        _render_default(
            runs,
            comparisons=comparisons,
            compare_requested=compare_requested,
            exit_code=exit_code,
            stdout=stdout,
        )

    return exit_code


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class _DiscoveryImportError(RuntimeError):
    """Discovery could not import the requested module."""


class _DiscoveryInvalidTargetError(RuntimeError):
    """Discovery resolved an attribute that is not an @Eval class."""


def _discover(targets: list[str]) -> list[type[Any]]:
    """Resolve every ``TARGET`` to a list of ``@Eval``-decorated classes.

    Discovery preserves declaration order across targets and modules,
    dedupes a class found through multiple targets (the class runs
    once), and raises one of the two private exceptions on any
    user-facing error so the caller can wrap them in a stable CLI
    message.
    """
    _ensure_cwd_on_sys_path()
    seen: dict[int, None] = {}
    ordered: list[type[Any]] = []
    for target in targets:
        for cls in _resolve_target(target):
            if id(cls) in seen:
                continue
            seen[id(cls)] = None
            ordered.append(cls)
    return ordered


def _ensure_cwd_on_sys_path() -> None:
    """Prepend the cwd to ``sys.path`` so user packages resolve.

    When the CLI is invoked from a project root via the
    ``ajolopy`` console-script entry point, ``sys.path`` does not
    include the cwd by default (unlike ``python -m`` invocations),
    so ``importlib.import_module("evals")`` fails to find a local
    ``evals/`` package. Match the behaviour of ``pytest`` / etc.
    by inserting the empty string at position 0 — Python resolves
    that lazily to the current working directory at import time.

    The insert is idempotent: if ``""`` (or the resolved cwd) is
    already on ``sys.path`` we leave the list untouched so repeated
    calls in the same process (tests, REPL) don't stack duplicates.
    """
    if "" in sys.path:
        return
    cwd = str(Path.cwd())
    if cwd in sys.path:
        return
    sys.path.insert(0, "")


def _resolve_target(target: str) -> list[type[Any]]:
    """Resolve a single ``TARGET`` to a list of ``@Eval`` classes."""
    if ":" in target:
        module_name, _, class_name = target.partition(":")
        module = _import_module(module_name)
        attr = getattr(module, class_name, None)
        if attr is None:
            raise _DiscoveryInvalidTargetError(
                f"attribute not found: {class_name!r} on module {module_name!r}."
            )
        if not _is_eval_class(attr):
            raise _DiscoveryInvalidTargetError(
                f"{target!r} is not an @Eval-decorated class. Decorate "
                f"{class_name} with @Eval(...) or pass a different target."
            )
        return [cast("type[Any]", attr)]

    module = _import_module(target)
    if hasattr(module, "__path__"):
        return _walk_package(module)
    return _classes_in_module(module)


def _import_module(module_name: str) -> Any:
    """Import ``module_name``; raise :class:`_DiscoveryImportError` on miss."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise _DiscoveryImportError(f"could not import {module_name!r}: {exc}.") from exc


def _walk_package(package: Any) -> list[type[Any]]:
    """Walk every submodule of ``package`` and collect @Eval classes."""
    classes: list[type[Any]] = []
    classes.extend(_classes_in_module(package))
    package_path = cast("list[str]", package.__path__)
    package_name = cast("str", package.__name__)
    for module_info in pkgutil.walk_packages(package_path, prefix=f"{package_name}."):
        try:
            submodule = importlib.import_module(module_info.name)
        except ImportError as exc:
            raise _DiscoveryImportError(
                f"could not import submodule {module_info.name!r}: {exc}."
            ) from exc
        classes.extend(_classes_in_module(submodule))
    return classes


def _classes_in_module(module: Any) -> list[type[Any]]:
    """Return ``@Eval`` classes declared on ``module``'s ``__dict__``.

    Filters by ``__module__`` so a class re-exported from another
    module via ``from x import Y`` is only counted in the module where
    it was declared. This keeps the deduplication across multiple
    targets clean without resorting to id-based deduplication alone.
    """
    found: list[type[Any]] = []
    module_name = cast("str", getattr(module, "__name__", ""))
    module_dict = cast("dict[str, object]", vars(module))
    for value in module_dict.values():
        if not _is_eval_class(value):
            continue
        cls = cast("type[Any]", value)
        if cls.__module__ != module_name:
            # Re-exported. Ignore here; the originating module's walk
            # will pick it up.
            continue
        found.append(cls)
    return found


def _is_eval_class(value: object) -> bool:
    """``True`` when ``value`` is a class carrying ``_ajolopy_eval`` metadata."""
    if not isinstance(value, type):
        return False
    return isinstance(getattr(value, EVAL_MARKER, None), EvalMetadata)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _filter_suites(suites: list[type[Any]], pattern: str) -> list[type[Any]]:
    """Keep suites whose class name matches ``pattern`` (case-insensitive)."""
    needle = pattern.lower()
    return [cls for cls in suites if fnmatch.fnmatchcase(cls.__name__.lower(), needle)]


# ---------------------------------------------------------------------------
# Runner orchestration
# ---------------------------------------------------------------------------


def _invocation_timestamp() -> str:
    """One shared timestamp for every run produced by this invocation."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _run_suites(
    suites: list[type[Any]],
    *,
    runner: EvalRunner,
    timestamp: str,
    save_dir: Path,
    no_save: bool,
    threshold_override: float | None,
) -> list[EvalRun]:
    """Run each suite sequentially; persist unless ``no_save`` is set."""
    runs: list[EvalRun] = []
    for suite_cls in suites:
        runnable_cls = _apply_threshold_override(suite_cls, threshold_override)
        run = asyncio.run(runner.run(runnable_cls))
        if not no_save:
            target_path = (Path(save_dir) / f"{timestamp}-{run.suite}.json").resolve()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            run.save(target_path)
        runs.append(run)
    return runs


def _apply_threshold_override(
    suite_cls: type[Any],
    threshold_override: float | None,
) -> type[Any]:
    """Return a class with an overridden threshold, or the original.

    The override is materialised as a dynamic subclass that shadows
    ``_ajolopy_eval`` with a :func:`dataclasses.replace` copy of the
    original metadata. Subclassing avoids mutating the user's frozen
    :class:`EvalMetadata` instance and keeps the original class
    unchanged for the rest of the process — important when multiple
    invocations share an import (tests, REPL).
    """
    if threshold_override is None:
        return suite_cls
    original_metadata = cast("EvalMetadata", getattr(suite_cls, EVAL_MARKER))
    new_metadata = dataclasses.replace(original_metadata, threshold=threshold_override)
    return type(
        suite_cls.__name__,
        (suite_cls,),
        {
            EVAL_MARKER: new_metadata,
            "__module__": suite_cls.__module__,
            "__qualname__": suite_cls.__qualname__,
        },
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _compare_runs(
    runs: list[EvalRun],
    *,
    compare_with: str,
    save_dir: Path,
    current_timestamp: str,
    stderr: IO[str],
) -> dict[str, EvalComparison | None]:
    """Resolve a prior run per suite and diff via :func:`compare_runs`."""
    comparisons: dict[str, EvalComparison | None] = {}
    for run in runs:
        prior_path = _resolve_compare_path(
            compare_with=compare_with,
            save_dir=save_dir,
            suite_name=run.suite,
            current_timestamp=current_timestamp,
        )
        if prior_path is None:
            comparisons[run.suite] = None
            continue
        try:
            prev = load_eval_run(prior_path)
            comparisons[run.suite] = compare_runs(prev, run)
        except EvalComparisonError as exc:
            print(
                f"ajolopy eval: skipping comparison for {run.suite}: {exc}",
                file=stderr,
            )
            comparisons[run.suite] = None
    return comparisons


def _resolve_compare_path(
    *,
    compare_with: str,
    save_dir: Path,
    suite_name: str,
    current_timestamp: str,
) -> Path | None:
    """Map a ``--compare-with`` value to a concrete file path, or ``None``."""
    # Form 3: filesystem directory (preferred when the value resolves to one).
    candidate_dir = Path(compare_with)
    if candidate_dir.is_dir():
        matches = sorted(candidate_dir.glob(f"*-{suite_name}.json"))
        return matches[-1] if matches else None

    # Form 1: ``last`` — most recent matching file in ``save_dir``.
    if compare_with == "last":
        save_path = Path(save_dir)
        if not save_path.is_dir():
            return None
        matches = sorted(
            p
            for p in save_path.glob(f"*-{suite_name}.json")
            if _timestamp_prefix(p.name) < current_timestamp
        )
        return matches[-1] if matches else None

    # Form 2: explicit timestamp prefix.
    save_path = Path(save_dir)
    if not save_path.is_dir():
        return None
    candidate = save_path / f"{compare_with}-{suite_name}.json"
    return candidate if candidate.is_file() else None


def _timestamp_prefix(filename: str) -> str:
    """Return the timestamp prefix from ``<timestamp>-<SuiteName>.json``."""
    # The filename layout is exactly ``<ts>-<suite>.json``; ``rpartition``
    # on the last ``-`` would split timestamps that happen to contain a
    # dash. Walk the documented prefix length instead.
    # Timestamp format produced by :func:`_invocation_timestamp`:
    # ``YYYY-MM-DDTHH-MM-SSZ`` (20 chars).
    return filename[:20]


# ---------------------------------------------------------------------------
# Exit-code computation
# ---------------------------------------------------------------------------


def _compute_exit_code(
    runs: list[EvalRun],
    comparisons: dict[str, EvalComparison | None],
) -> int:
    """Return ``EXIT_OK`` only when every suite passed AND no regressions."""
    for run in runs:
        if not run.passed:
            return EXIT_FAILED
    for comparison in comparisons.values():
        if comparison is None:
            continue
        if any(delta.is_regression for delta in comparison.metric_deltas.values()):
            return EXIT_FAILED
    return EXIT_OK


# ---------------------------------------------------------------------------
# Default (rich / plain) rendering
# ---------------------------------------------------------------------------


def _is_tty(stream: IO[str]) -> bool:
    """``True`` when ``stream`` is a real TTY.

    :class:`io.StringIO` raises :class:`io.UnsupportedOperation` from
    :meth:`fileno`. We treat any failure as "not a TTY" so the
    test-buffer path renders plain ASCII.
    """
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError, ValueError:
        return False


def _render_default(
    runs: list[EvalRun],
    *,
    comparisons: dict[str, EvalComparison | None],
    compare_requested: bool,
    exit_code: int,
    stdout: IO[str],
) -> None:
    """Write the rich (TTY) / plain (non-TTY) summary to ``stdout``."""
    use_colour = _is_tty(stdout)
    print(f"Running {len(runs)} eval suite(s)...", file=stdout)
    print("", file=stdout)

    passed_count = 0
    failed_count = 0
    regression_count = 0
    regression_lines: list[str] = []

    for run in runs:
        comparison = comparisons.get(run.suite)
        regressed_metrics = _regressed_metrics(comparison)
        status = _suite_status(run.passed, regressed_metrics)
        glyph = _status_glyph(status, use_colour=use_colour)
        badge_parts: list[str] = []
        if compare_requested and comparison is None:
            badge_parts.append(_decorate("NEW", _ANSI_YELLOW, use_colour))
        if regressed_metrics:
            badge_parts.append(_decorate("REGRESSION", _ANSI_YELLOW, use_colour))
            regression_count += len(regressed_metrics)

        score = f"{run.aggregate_score:.3f}"
        threshold = f"{run.threshold:.3f}"
        line = (
            f"{glyph} {run.suite}  -> score: {score} "
            f"(threshold: {threshold})  [{len(run.cases)} cases]"
        )
        if badge_parts:
            line += "  " + "  ".join(badge_parts)
        print(line, file=stdout)

        if run.passed:
            passed_count += 1
        else:
            failed_count += 1

        if comparison is not None:
            for metric_name in regressed_metrics:
                metric_delta = comparison.metric_deltas[metric_name]
                regression_lines.append(
                    f"{run.suite} regressed: {metric_name}="
                    f"{metric_delta.curr_aggregate:.3f} "
                    f"(was {metric_delta.prev_aggregate:.3f} in last run)"
                )

    print("", file=stdout)
    summary = f"Summary: {passed_count} passed, {failed_count} failed"
    if regression_count > 0:
        summary += f", {regression_count} regression(s)"
    print(summary, file=stdout)
    for line in regression_lines:
        print(line, file=stdout)
    print(f"Exit code: {exit_code}", file=stdout)


def _suite_status(passed: bool, regressed_metrics: list[str]) -> str:
    if not passed:
        return "fail"
    if regressed_metrics:
        return "warn"
    return "pass"


def _status_glyph(status: str, *, use_colour: bool) -> str:
    """Return the per-status glyph; emoji for TTY, ASCII badge otherwise."""
    if use_colour:
        if status == "pass":
            return _decorate("✅", _ANSI_GREEN, use_colour=True)
        if status == "warn":
            return _decorate("⚠️", _ANSI_YELLOW, use_colour=True)
        return _decorate("❌", _ANSI_RED, use_colour=True)
    if status == "pass":
        return "[PASS]"
    if status == "warn":
        return "[WARN]"
    return "[FAIL]"


def _decorate(text: str, colour: str, use_colour: bool) -> str:
    """Wrap ``text`` in ANSI codes when ``use_colour`` is set."""
    if not use_colour:
        return text
    return f"{_ANSI_BOLD}{colour}{text}{_ANSI_RESET}"


def _regressed_metrics(comparison: EvalComparison | None) -> list[str]:
    """Return the sorted names of metrics that regressed in ``comparison``."""
    if comparison is None:
        return []
    return sorted(name for name, delta in comparison.metric_deltas.items() if delta.is_regression)


# ---------------------------------------------------------------------------
# CI (JSON) rendering
# ---------------------------------------------------------------------------


def _render_ci(
    runs: list[EvalRun],
    *,
    comparisons: dict[str, EvalComparison | None],
    compare_requested: bool,
    timestamp: str,
    exit_code: int,
    stdout: IO[str],
) -> None:
    """Write the documented JSON snapshot to ``stdout``."""
    suite_blocks: list[dict[str, Any]] = []
    passed_count = 0
    failed_count = 0
    total_regressions = 0
    for run in runs:
        comparison = comparisons.get(run.suite) if compare_requested else None
        regressed = _regressed_metrics(comparison)
        total_regressions += len(regressed)
        if not compare_requested:
            compared_with: str | None = None
        else:
            compared_with = _compared_with_label(comparison) if comparison is not None else None
        suite_blocks.append(
            {
                "name": run.suite,
                "cases": len(run.cases),
                "metrics": {
                    name: {
                        "aggregator": metric.aggregator,
                        "aggregate": metric.aggregate,
                        "passed": metric.passed,
                    }
                    for name, metric in run.metrics.items()
                },
                "aggregate_score": run.aggregate_score,
                "threshold": run.threshold,
                "passed": run.passed,
                "compared_with": compared_with,
                "regressions": regressed,
            }
        )
        if run.passed:
            passed_count += 1
        else:
            failed_count += 1

    payload: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": timestamp,
        "suites": suite_blocks,
        "passed": passed_count,
        "failed": failed_count,
        "regressions": total_regressions,
        "exit_code": exit_code,
    }
    json.dump(payload, stdout, indent=2)
    print("", file=stdout)


def _compared_with_label(comparison: EvalComparison) -> str:
    """Filename-style label for the ``compared_with`` JSON field."""
    return f"{comparison.prev_timestamp}-{comparison.suite}.json"


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def _handle_dry_run(
    suites: list[type[Any]],
    *,
    ci: bool,
    stdout: IO[str],
) -> int:
    """Compute estimates and either print + prompt (default) or emit JSON (CI)."""
    estimates = [_estimate_one_suite(cls) for cls in suites]

    if ci:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "dry_run": True,
            "suites": [
                {
                    "name": e.suite_name,
                    "cases": e.cases,
                    "model": e.model,
                    "estimated_cost_usd": e.total_cost_usd,
                    "known": e.known,
                }
                for e in estimates
            ],
            "total_estimated_cost_usd": _sum_known(estimates),
            "unknown_models": [e.model for e in estimates if not e.known],
        }
        json.dump(payload, stdout, indent=2)
        print("", file=stdout)
        return EXIT_OK

    _print_dry_run_table(estimates, stdout=stdout)
    answer = builtins.input("Proceed? (y/N) ")
    if answer.strip().lower() not in {"y", "yes"}:
        return EXIT_DRY_RUN_DECLINED
    # ``y`` (or ``yes``) — let the caller proceed with the run.
    return EXIT_OK


@dataclasses.dataclass(slots=True, frozen=True)
class _SuiteEstimate:
    """Per-suite cost estimate produced by ``--dry-run``."""

    suite_name: str
    cases: int
    model: str
    total_cost_usd: float | None
    known: bool
    has_async_metric: bool


def _estimate_one_suite(suite_cls: type[Any]) -> _SuiteEstimate:
    """Estimate the cost of one suite based on the active pricing catalog."""
    metadata = cast("EvalMetadata", getattr(suite_cls, EVAL_MARKER))
    case_count = _suite_case_count(metadata)
    model = _suite_model(metadata)
    has_async_metric = any(m.is_async for m in metadata.metrics.values())
    catalog = get_active_catalog()
    price = catalog.get(model) if model else None
    if price is None:
        return _SuiteEstimate(
            suite_name=suite_cls.__name__,
            cases=case_count,
            model=model or "<unknown>",
            total_cost_usd=None,
            known=False,
            has_async_metric=has_async_metric,
        )

    agent_cost = case_count * (
        INPUT_TOKEN_ESTIMATE * price.input_cost_per_token
        + OUTPUT_TOKEN_ESTIMATE * price.output_cost_per_token
    )
    judge_cost = 0.0
    if has_async_metric:
        judge_cost = case_count * (
            JUDGE_INPUT_TOKEN_ESTIMATE * price.input_cost_per_token
            + JUDGE_OUTPUT_TOKEN_ESTIMATE * price.output_cost_per_token
        )
    return _SuiteEstimate(
        suite_name=suite_cls.__name__,
        cases=case_count,
        model=model,
        total_cost_usd=agent_cost + judge_cost,
        known=True,
        has_async_metric=has_async_metric,
    )


def _suite_case_count(metadata: EvalMetadata) -> int:
    """Best-effort case count without booting the agent runtime.

    The runner instantiates the dataset on every call (live edits
    supported); dry-run mirrors that by re-resolving the spec here so
    the printed count matches what the run would see.
    """
    from ajolopy.eval.resolver import resolve_dataset

    dataset = resolve_dataset(metadata.dataset_spec)
    return len(list(iter(dataset)))


def _suite_model(metadata: EvalMetadata) -> str:
    """Return the primary model string for the suite's target.

    Agent targets carry ``_agent_runtime._models[0][0]``. Workflow
    targets do not advertise a primary model — we return an empty
    string and the caller treats it as ``unknown``.
    """
    target_cls = metadata.target_cls
    runtime = getattr(target_cls, "_agent_runtime", None)
    if runtime is None:
        return ""
    models = cast("list[tuple[str, Any]]", getattr(runtime, "_models", []))
    if not models:
        return ""
    return models[0][0]


def _print_dry_run_table(
    estimates: list[_SuiteEstimate],
    *,
    stdout: IO[str],
) -> None:
    """Render the per-suite dry-run cost breakdown."""
    total = 0.0
    known_count = 0
    unknown_count = 0
    for est in estimates:
        if not est.known or est.total_cost_usd is None:
            print(
                f"{est.suite_name} ({est.cases} cases) — model {est.model} not in pricing catalog",
                file=stdout,
            )
            print("  Estimated cost: unknown", file=stdout)
            unknown_count += 1
            continue
        print(f"{est.suite_name} ({est.cases} cases)", file=stdout)
        print(
            f"  Agent calls: {est.cases:>3}  (~${est.total_cost_usd:.4f} estimated)",
            file=stdout,
        )
        if est.has_async_metric:
            print(
                f"  LLM judges:  {est.cases:>3}  (judge calls bundled in the total)",
                file=stdout,
            )
        total += est.total_cost_usd
        known_count += 1
    print("", file=stdout)
    print(
        f"Total: ~${total:.4f} ({known_count} suite estimated, {unknown_count} unknown)",
        file=stdout,
    )


def _sum_known(estimates: Iterable[_SuiteEstimate]) -> float:
    """Sum the known-model cost estimates; ignore unknown entries."""
    return sum(e.total_cost_usd for e in estimates if e.known and e.total_cost_usd is not None)
