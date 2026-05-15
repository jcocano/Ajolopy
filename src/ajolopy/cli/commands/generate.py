"""``ajolopy generate <kind> <name>`` subcommand.

Writes one templated file (or, for the ``eval`` kind, a tiny pair of
files) for the chosen Ajolopy primitive into the appropriate location
inside an existing project.

The handler is split into four phases that mirror :mod:`ajolopy.cli.commands.new`:

1. **Validate** the ``kind`` (must be one of the seven supported
   primitives) and the ``name`` (snake_case, matches
   ``^[a-z][a-z0-9_]*$``). Bad input exits with :data:`EXIT_USAGE`.
2. **Resolve** the destination root. ``--path`` overrides the auto
   detection; otherwise the command looks for ``src/<single-package>/``
   in cwd (same convention as ``ajolopy dev``). Missing or ambiguous
   layouts exit with :data:`EXIT_NO_PROJECT`.
3. **Render** the per-kind template(s) into the destination root,
   refusing to overwrite an existing file unless ``--force`` is
   passed.
4. **Report** the rendered paths to ``stdout``.

Templates and the substitution context are shared with :mod:`new` via
:mod:`ajolopy.cli.commands._template_engine` so both scaffolders use
the same ``{{name}}`` / ``{{package_name}}`` rules.
"""

import argparse  # noqa: TC003 -- argparse.Namespace is used at runtime by argparse itself
import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final

from . import _template_engine

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

__all__ = [
    "EXIT_EXISTS",
    "EXIT_NO_PROJECT",
    "EXIT_OK",
    "EXIT_USAGE",
    "SUPPORTED_KINDS",
    "cmd_generate",
    "register",
]


# ---------------------------------------------------------------------------
# Exit codes (mirrored by the spec).
# ---------------------------------------------------------------------------
EXIT_OK: Final = 0
EXIT_NO_PROJECT: Final = 1
EXIT_EXISTS: Final = 1
EXIT_USAGE: Final = 2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class _FileSpec:
    """One file the generator must produce for a given ``kind``.

    ``template`` is the basename of the ``.tmpl`` (or raw companion)
    file inside ``_templates/generate/<kind>/``. ``destination`` is the
    rendered path relative to the project root (with the same
    ``__package__`` sentinel that :mod:`new` uses for path tokens).
    """

    template: str
    destination: str


# Dispatch table: kind -> ordered file specs.
#
# The destination paths use ``__package__`` as a sentinel for the
# auto-detected package name; the substitution layer in
# :mod:`_template_engine` rewrites it before the file is written.
_DISPATCH: Final[dict[str, tuple[_FileSpec, ...]]] = {
    "agent": (_FileSpec("agent.py.tmpl", "src/__package__/agents/{snake_name}.py"),),
    "tool": (_FileSpec("tool.py.tmpl", "src/__package__/tools/{snake_name}.py"),),
    "workflow": (_FileSpec("workflow.py.tmpl", "src/__package__/workflows/{snake_name}.py"),),
    "eval": (
        _FileSpec("eval.py.tmpl", "evals/{snake_name}_eval.py"),
        _FileSpec("dataset.jsonl", "evals/datasets/{snake_name}.jsonl"),
    ),
    "controller": (
        _FileSpec(
            "controller.py.tmpl",
            "src/__package__/controllers/{snake_name}_controller.py",
        ),
    ),
    "module": (_FileSpec("module.py.tmpl", "src/__package__/{snake_name}_module.py"),),
    "service": (
        _FileSpec(
            "service.py.tmpl",
            "src/__package__/services/{snake_name}_service.py",
        ),
    ),
}

SUPPORTED_KINDS: Final[tuple[str, ...]] = tuple(_DISPATCH.keys())


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------
def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``generate`` subparser to the dispatcher.

    ``_SubParsersAction`` is the documented type for argparse's
    subparser registry; the pyright ignore mirrors the convention used
    by every other ``ajolopy`` subcommand.
    """
    parser = sub.add_parser(
        "generate",
        help="Generate a single Ajolopy primitive file in an existing project.",
        description=(
            "Scaffold one file (or a small set) for the chosen kind into "
            "an existing Ajolopy project. Supported kinds: "
            f"{', '.join(SUPPORTED_KINDS)}."
        ),
    )
    parser.add_argument(
        "kind",
        metavar="KIND",
        help=(f"Primitive to scaffold. One of: {', '.join(SUPPORTED_KINDS)}."),
    )
    parser.add_argument(
        "name",
        metavar="NAME",
        help=("snake_case identifier for the generated artefact (regex ^[a-z][a-z0-9_]*$)."),
    )
    parser.add_argument(
        "--path",
        dest="path",
        default=None,
        metavar="DIR",
        help="Destination directory (defaults to auto-detected project root).",
    )
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Overwrite the target file when it already exists.",
    )
    parser.set_defaults(func=cmd_generate)


# ---------------------------------------------------------------------------
# Entry point — wired into argparse via ``set_defaults(func=...)``.
# ---------------------------------------------------------------------------
def cmd_generate(args: argparse.Namespace) -> int:
    """Dispatcher entry — runs the command against the live streams."""
    return _command(args, stdout=sys.stdout, stderr=sys.stderr, cwd=Path.cwd())


def _command(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
) -> int:
    """Orchestrate validate -> resolve root -> render -> report."""
    kind: str = args.kind
    name: str = args.name
    if kind not in _DISPATCH:
        print(
            f"ajolopy generate: unknown kind {kind!r}. "
            f"Expected one of: {', '.join(SUPPORTED_KINDS)}.",
            file=stderr,
        )
        return EXIT_USAGE
    if not _NAME_RE.fullmatch(name):
        print(
            f"ajolopy generate: name {name!r} must be snake_case (regex {_NAME_RE.pattern!r}).",
            file=stderr,
        )
        return EXIT_USAGE

    root_resolution = _resolve_root(args, cwd=cwd, stderr=stderr)
    if isinstance(root_resolution, int):
        return root_resolution
    root, package_name = root_resolution

    context = _build_context(kind=kind, name=name, package_name=package_name)
    file_specs = _DISPATCH[kind]

    # First pass: detect collisions so we never half-write a multi-file
    # generation (the ``eval`` kind produces two files).
    targets: list[Path] = []
    for spec in file_specs:
        rendered_destination = _template_engine.render_path(spec.destination, context).format(
            **context
        )
        target = root / rendered_destination
        targets.append(target)
        if target.exists() and not args.force:
            print(
                f"ajolopy generate: refusing to overwrite existing file: "
                f"{target}. Pass --force to overwrite.",
                file=stderr,
            )
            return EXIT_EXISTS

    template_root = resources.files(_TEMPLATE_ROOT_PACKAGE) / kind
    written: list[Path] = []
    for spec, target in zip(file_specs, targets, strict=True):
        entry = template_root / spec.template
        content = _template_engine.read_template(_as_traversable(entry), context)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)

    _report(written=written, cwd=cwd, stdout=stdout)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Root resolution
# ---------------------------------------------------------------------------
def _resolve_root(
    args: argparse.Namespace,
    *,
    cwd: Path,
    stderr: IO[str],
) -> tuple[Path, str] | int:
    """Return ``(project_root, package_name)`` or a numeric exit code.

    ``--path`` short-circuits autodetection; in that mode the package
    name defaults to the path's leaf so any template referencing
    ``__package__`` still has a sensible substitution. The directory is
    created on demand (mirrors the spec's "write to that path"
    acceptance test).
    """
    explicit: str | None = args.path
    if explicit is not None:
        root = Path(explicit)
        root.mkdir(parents=True, exist_ok=True)
        # When the override happens to point at a ``src/<pkg>/`` we
        # still want a real package name in the substitution map;
        # otherwise fall back to the directory name so templates do
        # not emit a literal ``__package__`` token.
        package = _detect_single_package(root)
        if package is None:
            package = root.name or "app"
        return (root, package)

    src_dir = cwd / "src"
    if not src_dir.is_dir():
        print(
            "ajolopy generate: no 'src/' directory found in the current "
            "working directory. Pass --path <dir>, or run from a "
            "project root.",
            file=stderr,
        )
        return EXIT_NO_PROJECT

    packages = _list_packages(src_dir)
    if not packages:
        print(
            "ajolopy generate: no Python package found under 'src/' "
            "(no subdirectory containing an __init__.py). Pass --path "
            "<dir> to point at an explicit target.",
            file=stderr,
        )
        return EXIT_NO_PROJECT
    if len(packages) > 1:
        listed = ", ".join(sorted(packages))
        print(
            f"ajolopy generate: multiple packages under 'src/' ({listed}). "
            f"Pass --path <dir> to pick one explicitly.",
            file=stderr,
        )
        return EXIT_NO_PROJECT

    return (cwd, packages[0])


def _detect_single_package(root: Path) -> str | None:
    """Return the single package under ``<root>/src/`` if exactly one exists."""
    src_dir = root / "src"
    if not src_dir.is_dir():
        return None
    packages = _list_packages(src_dir)
    if len(packages) == 1:
        return packages[0]
    return None


def _list_packages(src_dir: Path) -> list[str]:
    """Return every immediate subpackage of ``src_dir`` (excluding caches)."""
    found: list[str] = []
    for entry in src_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in {"__pycache__"} or entry.name.startswith("."):
            continue
        if (entry / "__init__.py").is_file():
            found.append(entry.name)
    return found


# ---------------------------------------------------------------------------
# Substitution context
# ---------------------------------------------------------------------------
def _build_context(*, kind: str, name: str, package_name: str) -> dict[str, str]:
    """Return the ``str.format`` substitution map for the chosen kind."""
    return {
        "kind": kind,
        "name": name,
        "snake_name": name,
        "class_name": _to_pascal_case(name),
        "package_name": package_name,
    }


def _to_pascal_case(snake: str) -> str:
    """Return ``snake`` rendered as ``PascalCase``."""
    return "".join(part.capitalize() for part in snake.split("_") if part)


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------
_TEMPLATE_ROOT_PACKAGE: Final = "ajolopy.cli.commands._templates.generate"


def _as_traversable(entry: Traversable) -> Traversable:
    """No-op cast helper so pyright keeps the ``Traversable`` lineage.

    :func:`importlib.resources.files` returns a :class:`Traversable`,
    but the ``/`` operator widens the static type to ``object`` in
    older typeshed snapshots. Going through this thin wrapper keeps
    every call site strictly typed without scattering ``cast`` calls.
    """
    return entry


# ---------------------------------------------------------------------------
# Output reporting
# ---------------------------------------------------------------------------
def _report(*, written: list[Path], cwd: Path, stdout: IO[str]) -> None:
    """Print one ``+ <path>`` line per produced file."""
    for path in written:
        try:
            display = path.relative_to(cwd)
        except ValueError:
            display = path
        print(f"  + {display}", file=stdout)
