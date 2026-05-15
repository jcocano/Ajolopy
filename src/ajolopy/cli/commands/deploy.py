"""``ajolopy deploy`` subcommand — emit per-target deploy manifests.

The command is a thin driver around the :mod:`ajolopy.cli.deploy`
registry: pick a target, build a :class:`DeployContext`, ask the
target to :meth:`DeployTarget.prepare` its files, then write them to
disk (or print them, on ``--dry-run``).

Targets are pure — every filesystem touch and every byte sent to
stdout lives here. That keeps the deploy package importable in
hermetic tests and lets AJ-42 / AJ-43 / AJ-44 / AJ-45 ship without
touching CLI surface.
"""

import argparse
import sys
import tomllib
from pathlib import Path
from typing import IO, Any, cast

from ajolopy.cli.deploy import (
    DeployContext,
    DeployFilesExistError,
    DeployResult,
    DeployTarget,
    DeployTargetError,
    DeployTargetNotFoundError,
    DeployUserAbortError,
    get_target,
    list_targets,
)

__all__ = [
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_USAGE",
    "EXIT_USER_ABORT",
    "cmd_deploy",
    "register",
]


# ---------------------------------------------------------------------------
# Exit-code constants — shared with the test suite so a rename here cascades.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_USER_ABORT = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3


# ---------------------------------------------------------------------------
# Defaults — kept in sync with the AJ-41 Dockerfile template.
# ---------------------------------------------------------------------------
_DEFAULT_PORT = 3000
_DEFAULT_APP_MODULE = "main:app"


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``deploy`` subparser to the dispatcher."""
    description = _build_help_description()
    parser = sub.add_parser(
        "deploy",
        help="Emit per-target deploy manifests (fly/railway/render/vercel/docker).",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        metavar="TARGET",
        help="Deploy target (see description above for the v0.1 list).",
    )
    parser.add_argument(
        "--out",
        dest="out_dir",
        default=None,
        metavar="PATH",
        help="Project root to write manifests into (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print manifests to stdout instead of writing them.",
    )
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Overwrite existing manifest files (default: refuse and hint).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        dest="yes",
        action="store_true",
        help="Skip interactive confirmation prompts (e.g. the vercel warning gate).",
    )
    parser.set_defaults(func=cmd_deploy)


def _build_help_description() -> str:
    """Render the multi-line description that lists every registered target."""
    lines = ["Emit per-target deploy manifests for v0.1 platforms.", "", "Targets:"]
    targets = list_targets()
    if not targets:  # pragma: no cover -- defensive; package import always registers.
        lines.append("  (no targets registered — import ajolopy.cli.deploy first)")
        return "\n".join(lines)
    name_width = max(len(t.name) for t in targets)
    for target in targets:
        lines.append(f"  {target.name.ljust(name_width)}   {target.description}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point invoked by the dispatcher.
# ---------------------------------------------------------------------------


def cmd_deploy(args: argparse.Namespace) -> int:
    """Dispatcher entry — drives the command against real stdout/stderr."""
    return _command(args, stdout=sys.stdout, stderr=sys.stderr, cwd=Path.cwd())


def _command(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
) -> int:
    """Resolve target + context, render files, write or dry-run, print next steps."""
    target_name = cast("str", args.target)
    try:
        target = get_target(target_name)
    except DeployTargetNotFoundError as exc:
        print(str(exc), file=stderr)
        return EXIT_USAGE

    out_dir_raw = cast("str | None", args.out_dir)
    project_root = (cwd if out_dir_raw is None else Path(out_dir_raw)).resolve()
    if not project_root.is_dir():
        print(
            f"ajolopy deploy: --out {project_root} does not exist or is not a directory.",
            file=stderr,
        )
        return EXIT_USAGE

    try:
        ctx = _build_context(args, project_root=project_root, stdout=stdout)
    except DeployUserAbortError as exc:
        print(str(exc), file=stderr)
        return EXIT_USER_ABORT
    except DeployTargetError as exc:
        print(str(exc), file=stderr)
        return EXIT_INTERNAL

    try:
        result = target.prepare(ctx)
    except DeployUserAbortError as exc:
        print(str(exc), file=stderr)
        return EXIT_USER_ABORT
    except DeployTargetError as exc:
        print(f"ajolopy deploy: target {target_name!r} failed: {exc}", file=stderr)
        return EXIT_INTERNAL

    try:
        _validate_paths(result)
    except DeployTargetError as exc:
        print(str(exc), file=stderr)
        return EXIT_INTERNAL

    if ctx.dry_run:
        _print_dry_run(result, stdout=stdout)
    else:
        try:
            _write_files(result, ctx=ctx)
        except DeployFilesExistError as exc:
            print(str(exc), file=stderr)
            return EXIT_USAGE
        except OSError as exc:
            print(f"ajolopy deploy: failed to write manifest: {exc}", file=stderr)
            return EXIT_INTERNAL
        _print_written(result, ctx=ctx, stdout=stdout)

    _print_notes(result, stdout=stdout)
    _print_next_steps(target, ctx=ctx, result=result, stdout=stdout)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------


def _build_context(
    args: argparse.Namespace,
    *,
    project_root: Path,
    stdout: IO[str],
) -> DeployContext:
    """Compose the :class:`DeployContext` threaded into the target."""
    project_name = _resolve_project_name(project_root)
    app_module = _resolve_app_module(project_root)
    return DeployContext(
        project_root=project_root,
        app_module=app_module,
        port=_DEFAULT_PORT,
        python_version=_default_python_version(),
        project_name=project_name,
        is_tty=_is_tty(stdout),
        yes=bool(args.yes),
        dry_run=bool(args.dry_run),
        force=bool(args.force),
    )


def _resolve_project_name(project_root: Path) -> str:
    """Read ``[project] name`` from ``pyproject.toml`` or fall back to dir name."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.is_file():
        return project_root.name
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DeployTargetError(
            f"ajolopy deploy: failed to read {pyproject}: {exc}",
        ) from exc
    project_table = data.get("project")
    if isinstance(project_table, dict):
        # ``tomllib.loads`` returns ``dict[str, Any]``; narrow to ``Any``
        # to let pyright accept the heterogeneous ``.get`` call.
        table = cast("dict[str, Any]", project_table)
        name = table.get("name")
        if isinstance(name, str) and name:
            return name
    return project_root.name


def _resolve_app_module(project_root: Path) -> str:
    """Best-effort discovery of ``<package>.main:app``.

    Mirrors :func:`ajolopy.cli.commands.dev._resolve_autodetect` but
    falls back to the safe ``"main:app"`` default instead of erroring
    out — the deploy target only needs *a* module string for the
    Uvicorn command line, and the user can override the resulting
    Dockerfile by hand.
    """
    src_dir = project_root / "src"
    if not src_dir.is_dir():
        return _DEFAULT_APP_MODULE
    packages = [
        entry.name
        for entry in src_dir.iterdir()
        if entry.is_dir()
        and not entry.name.startswith(".")
        and entry.name != "__pycache__"
        and (entry / "__init__.py").is_file()
    ]
    if len(packages) != 1:
        return _DEFAULT_APP_MODULE
    package = packages[0]
    if not (src_dir / package / "main.py").is_file():
        return _DEFAULT_APP_MODULE
    return f"{package}.main:app"


def _default_python_version() -> str:
    """Return the current interpreter's ``X.Y`` version string."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


# ---------------------------------------------------------------------------
# Result validation + writing
# ---------------------------------------------------------------------------


def _validate_paths(result: DeployResult) -> None:
    """Reject absolute paths or paths that escape the project root."""
    for path in result.files:
        if path.is_absolute():
            raise DeployTargetError(
                f"ajolopy deploy: target emitted an absolute path {path!r}; "
                "only relative paths are allowed.",
            )
        if ".." in path.parts:
            raise DeployTargetError(
                f"ajolopy deploy: target emitted a traversal path {path!r}; '..' is not allowed.",
            )


def _write_files(result: DeployResult, *, ctx: DeployContext) -> None:
    """Write every file in ``result`` to disk, honouring ``--force``."""
    if not result.files:
        return
    targets: list[tuple[Path, str]] = [
        (ctx.project_root / rel, contents) for rel, contents in result.files.items()
    ]
    if not ctx.force:
        existing = [str(p.relative_to(ctx.project_root)) for p, _ in targets if p.exists()]
        if existing:
            listed = ", ".join(sorted(existing))
            raise DeployFilesExistError(
                f"ajolopy deploy: refusing to overwrite existing files: {listed}. "
                "Re-run with --force to overwrite.",
            )
    for path, contents in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


def _print_dry_run(result: DeployResult, *, stdout: IO[str]) -> None:
    """Echo every file in ``result`` to stdout with a ``# <path>`` header."""
    if not result.files:
        print("# (dry run) no files to write", file=stdout)
        return
    for path, contents in result.files.items():
        print(f"# {path}", file=stdout)
        print(contents, file=stdout)
        if not contents.endswith("\n"):
            print("", file=stdout)


def _print_written(result: DeployResult, *, ctx: DeployContext, stdout: IO[str]) -> None:
    """Confirm written files in a stable, scriptable format."""
    if not result.files:
        return
    print("Wrote:", file=stdout)
    for rel in result.files:
        # Path object renders identically across OSes for the relative
        # cases the deploy targets emit (single-segment filenames).
        print(f"  {ctx.project_root / rel}", file=stdout)


def _print_notes(result: DeployResult, *, stdout: IO[str]) -> None:
    """Print any informational notes (e.g. stub pointers at AJ-42/43/44/45)."""
    if not result.notes:
        return
    for note in result.notes:
        print(note, file=stdout)


def _print_next_steps(
    target: DeployTarget,
    *,
    ctx: DeployContext,
    result: DeployResult,
    stdout: IO[str],
) -> None:
    """Print the post-write instructions the target wants the user to run."""
    steps = list(target.next_steps(ctx, result))
    if not steps:
        return
    print("", file=stdout)
    print("Next steps:", file=stdout)
    for step in steps:
        print(f"  {step}", file=stdout)


def _is_tty(stream: IO[str]) -> bool:
    """Return ``True`` when ``stream`` is a real TTY (matches ``dev.py``)."""
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError, ValueError:
        return False
