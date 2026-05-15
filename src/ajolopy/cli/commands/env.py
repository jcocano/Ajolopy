"""``ajolopy env:show / env:validate / env:diff`` subcommands.

Three sibling commands share one module because they all introspect
the same artifact: the application's :class:`BaseConfig` subclass and
the project's ``.env`` files. The dispatcher registers them under the
argparse-friendly names ``env-show`` / ``env-validate`` / ``env-diff``
and rewrites the colon form (``env:show`` etc.) on the way in.

Each handler is split into pure helpers (``_discover_config``,
``_collect_vars``, ``_mask_value``, ``_parse_dotenv``) so the test
suite can assert against the rendered text and JSON payloads without
spinning a full project. The handlers themselves accept injected
``stdout`` / ``stderr`` streams plus a ``cwd`` :class:`Path` so the
CLI tests drive everything through :class:`io.StringIO` buffers.
"""

import argparse  # noqa: TC003 -- argparse.Namespace is used at runtime by argparse itself
import importlib
import inspect
import json
import os
import re
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, cast

from ajolopy.config import BaseConfig

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo


__all__ = [
    "COLON_FORM",
    "EXIT_DISCOVERY",
    "EXIT_FAILED",
    "EXIT_OK",
    "SCHEMA_VERSION",
    "SECRET_NAME_PATTERN",
    "cmd_env_diff",
    "cmd_env_show",
    "cmd_env_validate",
    "register",
]


# ---------------------------------------------------------------------------
# Exit codes — module-level so tests assert against names, not magic ints.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_DISCOVERY = 2


# ---------------------------------------------------------------------------
# CI JSON schema version. Bumped when the JSON shape changes in a
# non-additive way so downstream consumers can pin against it.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# User-facing colon form per internal parser name. Surfaced in help
# text so ``ajolopy env-show --help`` shows the documented invocation.
# ---------------------------------------------------------------------------
COLON_FORM: dict[str, str] = {
    "env-show": "env:show",
    "env-validate": "env:validate",
    "env-diff": "env:diff",
}


# Case-insensitive substring match — any field whose name contains one
# of these tokens is masked in :func:`_render_value`. The pattern is
# anchored to "word-like" segments so an unrelated identifier ending in
# "secrets_dir" still masks.
SECRET_NAME_PATTERN = re.compile(r"(key|token|password|secret)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Dispatcher registration
# ---------------------------------------------------------------------------


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the three ``env:*`` subparsers to the dispatcher.

    Each uses the hyphen form (``env-show`` etc.) internally because
    argparse subparser names cannot contain ``:``. The dispatcher's
    ``COLON_ALIASES`` rewrites ``argv`` so users still type the
    documented ``env:show`` form. The ``description=`` strings reflect
    the colon form so ``--help`` does not leak the alias.
    """
    _register_show(sub)
    _register_validate(sub)
    _register_diff(sub)


def _register_show(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    parser = sub.add_parser(
        "env-show",
        help="List every env var the app reads + whether it is set.",
        description=(
            "ajolopy env:show — list every env var declared on the app's "
            "BaseConfig subclass, marking each as set or missing. Values "
            "that look secret (name contains key/token/password/secret) "
            "are masked: only first 3 + last 4 chars + length are shown."
        ),
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Emit JSON to stdout instead of the TTY table.",
    )
    parser.set_defaults(func=cmd_env_show)


def _register_validate(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    parser = sub.add_parser(
        "env-validate",
        help="Run BaseConfig validation and report per-var pass/fail.",
        description=(
            "ajolopy env:validate — instantiate the app's BaseConfig "
            "subclass against os.environ + .env and report per-field "
            "errors. Exit 0 when every field validates, exit 1 if any "
            "field fails."
        ),
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Emit JSON to stdout instead of the TTY table.",
    )
    parser.set_defaults(func=cmd_env_validate)


def _register_diff(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    parser = sub.add_parser(
        "env-diff",
        help="Compare .env vs .env.example variable names.",
        description=(
            "ajolopy env:diff — compare the variable NAMES (not values) "
            "between .env and .env.example in the current working "
            "directory. Lists adds (in .env, not in .env.example) and "
            "removes (in .env.example, not in .env). Missing "
            ".env.example exits 1."
        ),
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Emit JSON to stdout instead of the TTY summary.",
    )
    parser.set_defaults(func=cmd_env_diff)


# ---------------------------------------------------------------------------
# Dispatcher entry points
# ---------------------------------------------------------------------------


def cmd_env_show(args: argparse.Namespace) -> int:
    """Dispatcher entry — drives ``env:show`` against real streams + cwd."""
    return _command_show(
        args,
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=Path.cwd(),
        environ=os.environ,
    )


def cmd_env_validate(args: argparse.Namespace) -> int:
    """Dispatcher entry — drives ``env:validate``."""
    return _command_validate(
        args,
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=Path.cwd(),
    )


def cmd_env_diff(args: argparse.Namespace) -> int:
    """Dispatcher entry — drives ``env:diff``."""
    return _command_diff(
        args,
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=Path.cwd(),
    )


# ---------------------------------------------------------------------------
# env:show command
# ---------------------------------------------------------------------------


def _command_show(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
    environ: os._Environ[str] | dict[str, str],  # pyright: ignore[reportPrivateUsage]
) -> int:
    """Discover the BaseConfig subclass, list every field, render output."""
    config_cls = _discover_config(cwd=cwd, stderr=stderr)
    if config_cls is None:
        return EXIT_DISCOVERY

    effective = _effective_env(cwd=cwd, environ=environ)
    rows = _collect_vars(config_cls, environ=effective)
    ci = bool(args.ci)
    if ci:
        _render_show_ci(rows, stdout=stdout)
    else:
        _render_show_text(rows, stdout=stdout)
    return EXIT_OK


def _effective_env(
    *,
    cwd: Path,
    environ: os._Environ[str] | dict[str, str],  # pyright: ignore[reportPrivateUsage]
) -> dict[str, str]:
    """Return a merged view of ``.env`` + process env (process env wins).

    Matches pydantic-settings's documented precedence so ``env:show``
    reflects exactly what ``BaseConfig()`` would see: variables in
    ``os.environ`` shadow same-named entries in ``.env``.
    """
    merged: dict[str, str] = {}
    env_path = cwd / ".env"
    if env_path.is_file():
        merged.update(_parse_dotenv_values(env_path))
    for key, value in environ.items():
        if not isinstance(value, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            continue
        merged[key] = value
    return merged


def _parse_dotenv_values(path: Path) -> dict[str, str]:
    """Return ``name → value`` for every well-formed entry in ``path``.

    Surface only the subset the diff parser already supports: key=value
    lines with optional ``export`` prefix, ``#`` comments stripped,
    matched single / double quotes around the value removed. Anything
    outside that surface is silently skipped so a malformed line never
    crashes ``env:show``.
    """
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if not _is_valid_env_name(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[name] = value
    return out


def _collect_vars(
    config_cls: type[BaseConfig],
    *,
    environ: os._Environ[str] | dict[str, str],  # pyright: ignore[reportPrivateUsage]
) -> list[dict[str, Any]]:
    """Return one descriptor per field of ``config_cls``.

    Each descriptor exposes ``name`` / ``set`` / ``length`` /
    ``masked_value``. Every value is masked through :func:`_mask_value`
    regardless of whether the name looks secret — the CLI MUST NOT
    print raw env-var contents to stdout (CodeQL flags any clear-text
    flow as a leak). The ``secret`` boolean stays as a hint for
    consumers of the JSON payload, but it never gates masking.
    """
    rows: list[dict[str, Any]] = []
    for name, info in config_cls.model_fields.items():
        raw = environ.get(name)
        if raw is None:
            rows.append(
                {
                    "name": name,
                    "set": False,
                    "length": 0,
                    "masked_value": None,
                    "secret": _looks_secret(name),
                    "required": _is_required(info),
                }
            )
            continue
        rows.append(
            {
                "name": name,
                "set": True,
                "length": len(raw),
                "masked_value": _mask_value(raw),
                "secret": _looks_secret(name),
                "required": _is_required(info),
            }
        )
    return rows


def _looks_secret(name: str) -> bool:
    """Case-insensitive check for secret-looking variable names."""
    return SECRET_NAME_PATTERN.search(name) is not None


def _is_required(info: FieldInfo) -> bool:
    """Return whether ``info`` describes a required field.

    Pydantic exposes :meth:`FieldInfo.is_required`; calling it through
    the public API keeps the helper resilient to internal layout
    changes between pydantic minor versions.
    """
    return bool(info.is_required())


def _mask_value(value: str) -> str:
    """Mask ``value`` returning only its length signature.

    Zero bytes of ``value`` reach the returned string — only the
    integer length does. CodeQL's clear-text-logging-sensitive-data
    rule treats any substring of an env-var read as a leak, so even
    a first-3/last-4 sketch like ``sk-…abcd`` propagates the taint.
    Stripping every byte of content is the only form that satisfies
    the rule across every callable that prints the masked output.
    """
    return f"({len(value)} chars)"


def _render_show_text(rows: list[dict[str, Any]], *, stdout: IO[str]) -> None:
    """Render the human-readable ``env:show`` table."""
    if not rows:
        print("ajolopy env:show: no fields declared on the discovered BaseConfig.", file=stdout)
        return
    use_unicode = _is_tty(stdout)
    set_glyph = "✓" if use_unicode else "[set]"
    missing_glyph = "✗" if use_unicode else "[missing]"
    width = max(len(cast("str", row["name"])) for row in rows)
    for row in rows:
        name = cast("str", row["name"])
        padded = name.ljust(width)
        if row["set"]:
            display = cast("str", row["masked_value"])
            print(f"{padded}  {set_glyph} set      ({display})", file=stdout)
        else:
            print(f"{padded}  {missing_glyph} missing", file=stdout)


def _render_show_ci(rows: list[dict[str, Any]], *, stdout: IO[str]) -> None:
    """Render the ``--ci`` JSON payload for ``env:show``.

    The payload deliberately omits any byte of the raw value. Length
    + presence + secret/required hints are enough for CI tooling to
    catch misconfiguration without flowing env-var contents to
    stdout (which CodeQL flags as a clear-text leak).
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "subcommand": "env:show",
        "vars": [
            {
                "name": row["name"],
                "set": row["set"],
                "length": row["length"],
                "secret": row["secret"],
                "required": row["required"],
            }
            for row in rows
        ],
        "exit_code": EXIT_OK,
    }
    print(json.dumps(payload, indent=2), file=stdout)


# ---------------------------------------------------------------------------
# env:validate command
# ---------------------------------------------------------------------------


def _command_validate(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
) -> int:
    """Discover the BaseConfig subclass, attempt instantiation, render results."""
    config_cls = _discover_config(cwd=cwd, stderr=stderr)
    if config_cls is None:
        return EXIT_DISCOVERY

    errors: list[dict[str, Any]] = []
    valid_fields: list[str] = list(config_cls.model_fields.keys())
    try:
        config_cls()
    except Exception as exc:
        # Catch broadly — pydantic-settings raises ValidationError, but
        # subclasses can surface other Exceptions during validators.
        errors = _extract_field_errors(exc, known_fields=valid_fields)
        if not errors:
            print(f"ajolopy env:validate: {type(exc).__name__}: {exc}", file=stderr)
            return EXIT_FAILED

    invalid_names = {entry["field"] for entry in errors}
    valid_names = [name for name in valid_fields if name not in invalid_names]
    exit_code = EXIT_FAILED if errors else EXIT_OK
    ci = bool(args.ci)
    if ci:
        _render_validate_ci(
            valid=valid_names,
            errors=errors,
            exit_code=exit_code,
            stdout=stdout,
        )
    else:
        _render_validate_text(
            valid=valid_names,
            errors=errors,
            stdout=stdout,
        )
    return exit_code


def _extract_field_errors(
    exc: Exception,
    *,
    known_fields: list[str],
) -> list[dict[str, Any]]:
    """Best-effort extraction of per-field errors from a pydantic exception.

    Returns ``[]`` when ``exc`` is not a pydantic ``ValidationError`` so
    the caller can fall back to a generic message. Each entry has
    ``field`` + ``message`` keys.
    """
    # Pydantic's ValidationError lives in different submodules across
    # versions; the duck-typed ``errors()`` method is the public API.
    errors_attr = getattr(exc, "errors", None)
    if not callable(errors_attr):
        return []
    raw_errors = cast("list[dict[str, Any]]", errors_attr())
    extracted: list[dict[str, Any]] = []
    for entry in raw_errors:
        loc = entry.get("loc") or ()
        field = str(loc[0]) if loc else ""
        if not field or field not in known_fields:
            continue
        msg = str(entry.get("msg", "validation error"))
        extracted.append({"field": field, "message": msg})
    return extracted


def _render_validate_text(
    *,
    valid: list[str],
    errors: list[dict[str, Any]],
    stdout: IO[str],
) -> None:
    """Render the human-readable ``env:validate`` summary."""
    use_unicode = _is_tty(stdout)
    ok_glyph = "✓" if use_unicode else "[ok]"
    fail_glyph = "✗" if use_unicode else "[fail]"
    error_by_field = {entry["field"]: entry["message"] for entry in errors}
    ordered = [*valid, *(entry["field"] for entry in errors)]
    width = max((len(name) for name in ordered), default=0)
    for name in valid:
        padded = name.ljust(width)
        print(f"{ok_glyph} {padded}  valid", file=stdout)
    for entry in errors:
        name = cast("str", entry["field"])
        padded = name.ljust(width)
        msg = cast("str", error_by_field[name])
        print(f"{fail_glyph} {padded}  {msg}", file=stdout)
    print("", file=stdout)
    print(f"{len(valid)} valid, {len(errors)} invalid", file=stdout)


def _render_validate_ci(
    *,
    valid: list[str],
    errors: list[dict[str, Any]],
    exit_code: int,
    stdout: IO[str],
) -> None:
    """Render the ``--ci`` JSON payload for ``env:validate``."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "subcommand": "env:validate",
        "valid": list(valid),
        "errors": [{"field": entry["field"], "message": entry["message"]} for entry in errors],
        "exit_code": exit_code,
    }
    print(json.dumps(payload, indent=2), file=stdout)


# ---------------------------------------------------------------------------
# env:diff command
# ---------------------------------------------------------------------------


def _command_diff(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
) -> int:
    """Compare the variable NAMES between ``.env`` and ``.env.example``."""
    env_path = cwd / ".env"
    example_path = cwd / ".env.example"
    if not example_path.is_file():
        print(
            "ajolopy env:diff: .env.example not found in the current working "
            "directory. Add a tracked example file to enable diffing.",
            file=stderr,
        )
        return EXIT_FAILED

    env_names = _parse_dotenv(env_path) if env_path.is_file() else []
    example_names = _parse_dotenv(example_path)
    env_set = set(env_names)
    example_set = set(example_names)
    only_env = sorted(env_set - example_set)
    only_example = sorted(example_set - env_set)

    ci = bool(args.ci)
    if ci:
        _render_diff_ci(
            only_env=only_env,
            only_example=only_example,
            env_present=env_path.is_file(),
            stdout=stdout,
        )
        return EXIT_OK

    _render_diff_text(
        only_env=only_env,
        only_example=only_example,
        env_present=env_path.is_file(),
        stdout=stdout,
    )
    return EXIT_OK


def _parse_dotenv(path: Path) -> list[str]:
    """Return the variable NAMES (in declaration order) declared in ``path``.

    The parser deliberately does not handle every dotenv corner case
    (multi-line strings, ``export`` prefixes with semicolons, etc.) —
    only the documented surface of a key=value file with ``#`` comments
    and optional ``export`` prefixes. Anything outside that surface is
    silently skipped so a malformed line cannot crash the diff.
    """
    seen: dict[str, None] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if not name or not _is_valid_env_name(name):
            continue
        seen.setdefault(name, None)
    return list(seen.keys())


_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_valid_env_name(name: str) -> bool:
    """Return True if ``name`` matches the POSIX env-var name grammar."""
    return _ENV_NAME_PATTERN.match(name) is not None


def _render_diff_text(
    *,
    only_env: list[str],
    only_example: list[str],
    env_present: bool,
    stdout: IO[str],
) -> None:
    """Render the human-readable ``env:diff`` summary."""
    if not only_env and not only_example:
        if not env_present:
            print(
                "ajolopy env:diff: .env not found; .env.example declares "
                f"{len(only_example)} variables (no diff to show).",
                file=stdout,
            )
            return
        print("ajolopy env:diff: no differences.", file=stdout)
        return

    if only_env:
        print("In .env but NOT .env.example:", file=stdout)
        for name in only_env:
            print(f"  + {name}", file=stdout)
        if only_example:
            print("", file=stdout)
    if only_example:
        print("In .env.example but NOT .env:", file=stdout)
        for name in only_example:
            print(f"  - {name}", file=stdout)


def _render_diff_ci(
    *,
    only_env: list[str],
    only_example: list[str],
    env_present: bool,
    stdout: IO[str],
) -> None:
    """Render the ``--ci`` JSON payload for ``env:diff``."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "subcommand": "env:diff",
        "env_present": env_present,
        "adds": list(only_env),
        "removes": list(only_example),
        "exit_code": EXIT_OK,
    }
    print(json.dumps(payload, indent=2), file=stdout)


# ---------------------------------------------------------------------------
# BaseConfig discovery
# ---------------------------------------------------------------------------


def _discover_config(*, cwd: Path, stderr: IO[str]) -> type[BaseConfig] | None:
    """Return the project's :class:`BaseConfig` subclass or ``None``.

    Walks ``src/<package>/`` for a single Python package, imports
    ``<package>.app_module``, and returns the first
    :class:`BaseConfig` subclass declared in (or imported into) that
    module. ``None`` is returned after writing a user-facing hint to
    ``stderr``. Falls back to scanning ``<package>`` itself when
    ``app_module`` does not declare or import a config class.
    """
    src_dir = cwd / "src"
    if not src_dir.is_dir():
        print(
            "ajolopy env: no 'src/' directory found in the current working "
            "directory. Run from a project root scaffolded by 'ajolopy new'.",
            file=stderr,
        )
        return None

    packages = _list_packages(src_dir)
    if not packages:
        print(
            "ajolopy env: no Python package found under 'src/' (no "
            "subdirectory containing an __init__.py). Run 'ajolopy new' "
            "to scaffold one.",
            file=stderr,
        )
        return None
    if len(packages) > 1:
        listed = ", ".join(sorted(packages))
        print(
            f"ajolopy env: multiple packages under 'src/' ({listed}). "
            "Pick a project with a single top-level package, or extend the "
            "convention with explicit configuration in a future release.",
            file=stderr,
        )
        return None

    package = packages[0]
    _ensure_src_on_syspath(src_dir)

    module_name = f"{package}.app_module"
    config_cls = _find_config_in_module(module_name)
    if config_cls is not None:
        return config_cls

    # Fall back to the package root; tolerant of projects where the
    # config class is declared at top-level (``<package>/config.py``)
    # rather than in ``app_module.py``.
    config_cls = _find_config_in_module(package)
    if config_cls is not None:
        return config_cls

    print(
        f"ajolopy env: no BaseConfig subclass found in '{module_name}'. "
        "Declare a subclass of ajolopy.BaseConfig and import it into "
        "your AppModule so the CLI can discover it.",
        file=stderr,
    )
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


def _ensure_src_on_syspath(src_dir: Path) -> None:
    """Prepend ``src_dir`` to :data:`sys.path` so import resolves it."""
    src_str = str(src_dir.resolve())
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def _find_config_in_module(module_name: str) -> type[BaseConfig] | None:
    """Import ``module_name`` and return the first ``BaseConfig`` subclass.

    Returns ``None`` when the module cannot be imported, when it does
    not declare or import a :class:`BaseConfig` subclass, or when only
    :class:`BaseConfig` itself is exposed. Import failures are
    swallowed deliberately so the caller can surface a single
    consistent error message — the user-facing diagnostic lives in
    :func:`_discover_config`.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if obj is BaseConfig:
            continue
        if not issubclass(obj, BaseConfig):
            continue
        return obj
    return None


# ---------------------------------------------------------------------------
# Stream helpers
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
