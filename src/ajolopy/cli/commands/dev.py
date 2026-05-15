"""``ajolopy dev`` subcommand — uvicorn ``--reload`` wrapper.

The handler:

1. **Resolves** the entry point.

   - ``--app <module>:<var>`` overrides everything. Both halves are
     stripped of whitespace, the module is imported, and ``var`` is
     looked up on it.
   - With no ``--app``, the auto-detection algorithm from AJ-32's
     convention runs: ``src/<package>/main.py`` must exist with an
     ``app`` attribute, with EXACTLY ONE package under ``src/``.

2. **Builds a** :class:`uvicorn.Config` with the resolved target and
   the requested host / port / reload directories. ``.env`` watching
   is layered on top by adding the cwd to ``reload_dirs`` and
   filtering with ``reload_includes=["**/.env", "*.py"]`` so unrelated
   sibling files do not trigger a reload.

3. **Prints a banner** describing the resolved target + watched paths
   before handing off to :meth:`uvicorn.Server.run`. The banner skips
   emoji + colors on a non-TTY stdout (e.g. when piped to a file or
   captured by tests using :class:`io.StringIO`).

The orchestration is split into pure helpers (``_resolve_target``,
``_collect_watch_dirs``, ``_build_config``, ``_render_banner``) so
the test suite can assert against the produced :class:`uvicorn.Config`
without booting a real socket. The blocking ``server.run()`` call is
isolated in :func:`cmd_dev`; the programmatic smoke test exercises
:meth:`uvicorn.Server.serve` directly so it can interrupt cleanly.
"""

import argparse  # noqa: TC003 -- argparse.Namespace is used at runtime by argparse itself
import importlib
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from types import ModuleType

    import uvicorn

__all__ = [
    "EXIT_DISCOVERY",
    "EXIT_OK",
    "EXIT_USAGE",
    "cmd_dev",
    "register",
]


# ---------------------------------------------------------------------------
# Exit-code constants — shared with the test suite so a rename here cascades
# to the assertions.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_DISCOVERY = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``dev`` subparser to the dispatcher.

    ``_SubParsersAction`` is the documented type for argparse's
    subparser registry; the pyright ignore mirrors the convention used
    by every other ``ajolopy`` subcommand.
    """
    parser = sub.add_parser(
        "dev",
        help="Run the development server with hot-reload.",
        description=(
            "Start uvicorn with --reload against the project's ASGI app. "
            "Auto-detects src/<package>/main.py:app by default; override "
            "with --app <module>:<var>. Watches src/ and .env."
        ),
    )
    parser.add_argument(
        "--app",
        dest="app_target",
        default=None,
        metavar="MODULE:VAR",
        help="Explicit module:var entry point (default: auto-detect).",
    )
    parser.add_argument(
        "--host",
        dest="host",
        default=DEFAULT_HOST,
        metavar="HOST",
        help=f"Bind host (default: {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        default=DEFAULT_PORT,
        metavar="PORT",
        help=f"Bind port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--watch",
        dest="watch",
        action="append",
        default=None,
        metavar="PATH",
        help="Additional directory to watch for reload (repeatable).",
    )
    parser.add_argument(
        "--no-reload",
        dest="no_reload",
        action="store_true",
        help="Disable reload (useful when debugging the framework itself).",
    )
    parser.set_defaults(func=cmd_dev)


# ---------------------------------------------------------------------------
# Entry point invoked by the dispatcher.
# ---------------------------------------------------------------------------


def cmd_dev(args: argparse.Namespace) -> int:
    """Dispatcher entry — drives the dev server against real stdout/stderr."""
    return _command(args, stdout=sys.stdout, stderr=sys.stderr, cwd=Path.cwd())


def _command(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
) -> int:
    """Resolve, configure, render the banner, and run the server."""
    resolution = _resolve_target(args, cwd=cwd, stderr=stderr)
    if isinstance(resolution, int):
        return resolution
    module_name, var_name = resolution

    watch_dirs = _collect_watch_dirs(
        module_name=module_name,
        var_name=var_name,
        explicit_watches=cast("list[str] | None", args.watch),
        cwd=cwd,
        used_autodetect=args.app_target is None,
    )
    reload_enabled = not bool(args.no_reload)
    include_env = (cwd / ".env").is_file()
    if include_env:
        cwd_str = str(cwd)
        if cwd_str not in watch_dirs:
            watch_dirs.append(cwd_str)

    config = _build_config(
        module=module_name,
        var=var_name,
        host=cast("str", args.host),
        port=cast("int", args.port),
        reload=reload_enabled,
        reload_dirs=watch_dirs,
        include_env=include_env,
    )

    _render_banner(
        module=module_name,
        var=var_name,
        host=cast("str", args.host),
        port=cast("int", args.port),
        watch_dirs=watch_dirs,
        reload=reload_enabled,
        stdout=stdout,
    )

    server = _make_server(config)
    server.run()
    return EXIT_OK


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _resolve_target(
    args: argparse.Namespace,
    *,
    cwd: Path,
    stderr: IO[str],
) -> tuple[str, str] | int:
    """Return ``(module, var)`` for the requested entry point.

    The function returns an ``int`` exit code on any failure so the
    caller can propagate it directly. Successes are reported as a
    ``(module, var)`` tuple.
    """
    app_target = cast("str | None", args.app_target)
    if app_target is not None:
        return _resolve_explicit(app_target, stderr=stderr)
    return _resolve_autodetect(cwd=cwd, stderr=stderr)


def _resolve_explicit(target: str, *, stderr: IO[str]) -> tuple[str, str] | int:
    """Parse and import an explicit ``--app module:var`` target."""
    stripped = target.strip()
    if not stripped:
        print("ajolopy dev: --app value is empty.", file=stderr)
        return EXIT_USAGE
    parts = stripped.split(":")
    if len(parts) != 2:
        print(
            f"ajolopy dev: --app {target!r} is not in the expected 'module:var' format.",
            file=stderr,
        )
        return EXIT_USAGE
    module_name = parts[0].strip()
    var_name = parts[1].strip()
    if not module_name or not var_name:
        print(
            f"ajolopy dev: --app {target!r} is missing either the module "
            f"or the variable name. Expected 'module:var'.",
            file=stderr,
        )
        return EXIT_USAGE

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(
            f"ajolopy dev: could not import module {module_name!r}: {exc}.",
            file=stderr,
        )
        return EXIT_DISCOVERY
    if not hasattr(module, var_name):
        print(
            f"ajolopy dev: attribute {var_name!r} not found on module {module_name!r}.",
            file=stderr,
        )
        return EXIT_DISCOVERY
    return (module_name, var_name)


def _resolve_autodetect(*, cwd: Path, stderr: IO[str]) -> tuple[str, str] | int:
    """Run the AJ-32 convention discovery against ``cwd``.

    See the spec for the documented branches; each user-facing error
    prints a hint and returns :data:`EXIT_DISCOVERY` so the caller can
    propagate the exit code directly.
    """
    src_dir = cwd / "src"
    if not src_dir.is_dir():
        print(
            "ajolopy dev: no 'src/' directory found in the current "
            "working directory. Pass --app <module>:<var>, or run "
            "from a project root.",
            file=stderr,
        )
        return EXIT_DISCOVERY

    packages = _list_packages(src_dir)
    if not packages:
        print(
            "ajolopy dev: no Python package found under 'src/' (no "
            "subdirectory containing an __init__.py). Pass --app "
            "<module>:<var> to point at an explicit target.",
            file=stderr,
        )
        return EXIT_DISCOVERY
    if len(packages) > 1:
        listed = ", ".join(sorted(packages))
        print(
            f"ajolopy dev: multiple packages under 'src/' ({listed}). "
            f"Pass --app <module>:<var> to pick one explicitly.",
            file=stderr,
        )
        return EXIT_DISCOVERY

    package = packages[0]
    main_path = src_dir / package / "main.py"
    if not main_path.is_file():
        print(
            f"ajolopy dev: expected 'src/{package}/main.py' but the "
            f"file does not exist. Pass --app <module>:<var> to point "
            f"at a different entry point.",
            file=stderr,
        )
        return EXIT_DISCOVERY

    _ensure_src_on_syspath(src_dir)
    module_name = f"{package}.main"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(
            f"ajolopy dev: could not import {module_name!r}: {exc}.",
            file=stderr,
        )
        return EXIT_DISCOVERY

    if not hasattr(module, "app"):
        print(
            f"ajolopy dev: {module_name!r} does not define an 'app' "
            f"attribute. Build it with AjolopyFactory.create(AppModule) "
            f"and assign it to 'app' at module scope, or pass --app "
            f"<module>:<var> to point at a different entry point.",
            file=stderr,
        )
        return EXIT_DISCOVERY
    return (module_name, "app")


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


def _ensure_src_on_syspath(src_dir: Path) -> None:
    """Prepend ``src_dir`` to :data:`sys.path` so import resolves it."""
    src_str = str(src_dir.resolve())
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


# ---------------------------------------------------------------------------
# Watch-directory collection
# ---------------------------------------------------------------------------


def _collect_watch_dirs(
    *,
    module_name: str,
    var_name: str,  # noqa: ARG001 — accepted for symmetry; not yet used.
    explicit_watches: list[str] | None,
    cwd: Path,
    used_autodetect: bool,
) -> list[str]:
    """Return the ordered list of directories uvicorn should watch.

    - Auto-detect mode watches ``src/``.
    - ``--app`` mode watches the parent directory of the imported
      module's file (best effort — falls back to ``cwd`` when the
      module has no ``__file__``).
    - Every ``--watch <path>`` adds an extra directory.
    """
    dirs: list[str] = []
    if used_autodetect:
        dirs.append(str((cwd / "src").resolve()))
    else:
        module = sys.modules.get(module_name)
        parent = _module_parent_dir(module, fallback=cwd)
        dirs.append(str(parent.resolve()))

    if explicit_watches:
        for path in explicit_watches:
            resolved = str(Path(path).resolve())
            if resolved not in dirs:
                dirs.append(resolved)
    return dirs


def _module_parent_dir(module: ModuleType | None, *, fallback: Path) -> Path:
    """Return the directory containing ``module``'s source file, or fallback."""
    if module is None:
        return fallback
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return fallback
    return Path(cast("str", module_file)).resolve().parent


# ---------------------------------------------------------------------------
# uvicorn integration
# ---------------------------------------------------------------------------


def _build_config(
    *,
    module: str,
    var: str,
    host: str,
    port: int,
    reload: bool,
    reload_dirs: list[str],
    include_env: bool,
) -> uvicorn.Config:
    """Build the :class:`uvicorn.Config` driving the dev server.

    Imported lazily so ``ajolopy --help`` does not pay uvicorn's
    import cost on every invocation.
    """
    import uvicorn

    kwargs: dict[str, Any] = {
        "app": f"{module}:{var}",
        "host": host,
        "port": port,
        "reload": reload,
    }
    if reload:
        kwargs["reload_dirs"] = list(reload_dirs)
        if include_env:
            # Filter so the cwd entry only triggers on ``.env`` + ``.py``
            # files; otherwise every unrelated edit in the project root
            # would bounce the server.
            kwargs["reload_includes"] = ["**/.env", "*.py"]
    return uvicorn.Config(**kwargs)


def _make_server(config: uvicorn.Config) -> uvicorn.Server:
    """Build a :class:`uvicorn.Server`; isolated for test seam."""
    import uvicorn

    return uvicorn.Server(config)


# ---------------------------------------------------------------------------
# Banner rendering
# ---------------------------------------------------------------------------


def _render_banner(
    *,
    module: str,
    var: str,
    host: str,
    port: int,
    watch_dirs: list[str],
    reload: bool,
    stdout: IO[str],
) -> None:
    """Write the connection-info banner before uvicorn output appears."""
    use_emoji = _is_tty(stdout)
    header = (
        "\U0001f4e1 Starting Ajolopy dev server..."
        if use_emoji
        else "Starting Ajolopy dev server..."
    )
    print(header, file=stdout)
    print(f"   App:      {module}:{var}", file=stdout)
    print(f"   URL:      http://{host}:{port}", file=stdout)
    print(f"   Watching: {_format_watch_dirs(watch_dirs)}", file=stdout)
    print(f"   Reload:   {'on' if reload else 'off'}", file=stdout)
    print("", file=stdout)


def _format_watch_dirs(watch_dirs: list[str]) -> str:
    """Render a comma-separated, relative-when-possible directory list."""
    if not watch_dirs:
        return "(none)"
    formatted: list[str] = []
    cwd = Path.cwd()
    for entry in watch_dirs:
        path = Path(entry)
        try:
            formatted.append(str(path.relative_to(cwd)))
        except ValueError:
            formatted.append(str(path))
    return ", ".join(formatted)


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
