"""``ajolopy doctor`` subcommand.

Runs a fixed, ordered list of 12 diagnostic checks against the current
working directory + process environment, then prints a per-check report
and exits non-zero on any failure. The Brief calls this the "lighthouse
for AI apps": one command that tells the user whether their project is
healthy enough to boot.

Architecture
------------

The module is split into three layers so the test suite can drive each
in isolation:

1. **Checks** — small classes, one per diagnostic. Each implements
   ``name: str`` + ``async def run() -> CheckResult``. ``CheckResult``
   carries ``passed`` (``True`` / ``False`` / ``None`` for skipped),
   ``status`` (``ok`` / ``fail`` / ``warn`` / ``skip``), ``message``,
   and ``duration_ms``.

2. **Runner** — :func:`_run_checks` iterates the list in declaration
   order, honours ``--skip``, captures duration per check, and
   aggregates the summary counts. Network-aware checks all wrap their
   work in :func:`asyncio.wait_for` so the spec's 30-second total
   ceiling holds even when DNS is broken.

3. **Renderer** — :func:`_render_tty` writes the emoji table to stdout
   for a real TTY; :func:`_render_ci` dumps the JSON document defined
   in the spec for ``--ci``. The two share :class:`_RunReport` so the
   exit-code math is computed once.

The 12 checks (in the spec's order):

1. ``python_version``     — interpreter ``>= 3.14``.
2. ``ajolopy_installed``  — ``import ajolopy`` succeeds, prints version.
3. ``venv_present``       — ``.venv/`` in cwd OR ``VIRTUAL_ENV`` set.
4. ``pyproject_present``  — ``pyproject.toml`` in cwd.
5. ``project_structure``  — ``src/<pkg>/main.py`` discoverable.
6. ``env_file_present``   — ``.env`` exists (warning otherwise).
7. ``env_validation``     — ``BaseConfig`` instantiates with no error
   (warning when no project-level subclass exists yet).
8. ``anthropic_api_key``  — key present + ``provider.health_check()``
   succeeds (warning on network failure, skipped when not configured).
9. ``openai_api_key``     — analogous for OpenAI.
10. ``gemini_api_key``     — analogous for Gemini.
11. ``otel_endpoint``      — ``OTEL_EXPORTER_OTLP_ENDPOINT`` reachable
    if set; warning when unset; warning on network failure.
12. ``mcp_servers``        — every ``@MCP``-decorated class connects
    within ``5s`` (warning per server on failure, skipped when there
    are no @MCP classes in the registry).
"""

import argparse  # noqa: TC003 -- argparse.Namespace is used at runtime by argparse itself
import asyncio
import importlib
import json
import os
import socket
import sys
import time
import urllib.parse
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, ClassVar, Literal, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ajolopy.config import BaseConfig


__all__ = [
    "EXIT_FAIL",
    "EXIT_OK",
    "CheckResult",
    "cmd_doctor",
    "register",
]


# ---------------------------------------------------------------------------
# Exit-code constants — shared with the test suite so a rename here cascades
# to assertions.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_FAIL = 1


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Per-check network timeout. The spec mandates 5s for the MCP probe; we
# reuse the same ceiling for the provider health checks and the OTel
# reachability probe so the total runtime is bounded at ~30s even in the
# worst case (every network check timing out simultaneously).
_NETWORK_TIMEOUT_S = 5.0

# JSON schema version emitted by ``--ci``. Bump whenever the document
# shape changes so CI consumers can switch on it.
_CI_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# CheckResult — the value every check returns.
# ---------------------------------------------------------------------------

Status = Literal["ok", "fail", "warn", "skip"]


@dataclass(slots=True, frozen=True)
class CheckResult:
    """Outcome of a single diagnostic check.

    Attributes
    ----------
    name
        Stable identifier for the check; surfaces in ``--skip`` and the
        ``--ci`` JSON.
    passed
        ``True`` for a success, ``False`` for a failure, ``None`` when
        the check was skipped or registered a non-fatal warning that
        does not flip the global exit code. The terminology is split
        from ``status`` because the JSON consumer needs a tri-state.
    status
        Renderer-facing label. ``ok`` / ``fail`` / ``warn`` / ``skip``.
    message
        Single-line human-readable summary. The renderer truncates if
        the column width demands it; the JSON output preserves it
        verbatim.
    duration_ms
        Wallclock duration of the check, measured by the runner.
    """

    name: str
    passed: bool | None
    status: Status
    message: str
    duration_ms: float


# ---------------------------------------------------------------------------
# Check protocol — every check is a small class with two members.
# ---------------------------------------------------------------------------


@runtime_checkable
class Check(Protocol):
    """Structural interface every diagnostic check implements.

    Checks live as classes (not functions) so they can carry per-check
    configuration (the ``provider_key`` / ``env_var`` pair of the
    provider health checks, for example) without the runner having to
    know about it.
    """

    name: str

    async def run(self) -> tuple[bool | None, str]:
        """Execute the check; return ``(passed, message)``.

        ``passed`` is tri-state: ``True`` for pass, ``False`` for fail,
        ``None`` for "skipped / warning, do not flip the exit code".
        The runner pairs this with the duration + maps the tri-state to
        a :class:`Status` label.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


class PythonVersionCheck:
    """Check 1 — interpreter version ``>= 3.14``."""

    name = "python_version"

    async def run(self) -> tuple[bool | None, str]:
        ver = sys.version_info
        rendered = f"Python {ver.major}.{ver.minor}.{ver.micro}"
        if (ver.major, ver.minor) < (3, 14):
            return False, f"{rendered} < 3.14 (required by ajolopy)"
        return True, rendered


class AjolopyInstalledCheck:
    """Check 2 — ``ajolopy`` is importable; report its version."""

    name = "ajolopy_installed"

    async def run(self) -> tuple[bool | None, str]:
        try:
            module = importlib.import_module("ajolopy")
        except ImportError as exc:
            return False, f"could not import ajolopy: {exc}"
        version = getattr(module, "__version__", "unknown")
        return True, f"version {version}"


class VenvPresentCheck:
    """Check 3 — ``.venv/`` in cwd OR ``VIRTUAL_ENV`` set."""

    name = "venv_present"

    def __init__(self, *, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self) -> tuple[bool | None, str]:
        if (self._cwd / ".venv").is_dir():
            return True, ".venv/"
        if os.environ.get("VIRTUAL_ENV"):
            return True, f"VIRTUAL_ENV={os.environ['VIRTUAL_ENV']}"
        return None, "no .venv/ and VIRTUAL_ENV not set"


class PyprojectPresentCheck:
    """Check 4 — ``pyproject.toml`` exists in cwd."""

    name = "pyproject_present"

    def __init__(self, *, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self) -> tuple[bool | None, str]:
        if (self._cwd / "pyproject.toml").is_file():
            return True, "pyproject.toml in cwd"
        return False, "pyproject.toml not found in cwd"


class ProjectStructureCheck:
    """Check 5 — ``src/<pkg>/main.py`` is discoverable.

    Mirrors the AJ-32 autodetect convention used by ``ajolopy dev``:
    exactly one package under ``src/`` carrying a ``main.py``.
    """

    name = "project_structure"

    def __init__(self, *, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self) -> tuple[bool | None, str]:
        src_dir = self._cwd / "src"
        if not src_dir.is_dir():
            return False, "src/ directory not found"
        packages: list[str] = []
        for entry in src_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name == "__pycache__":
                continue
            if (entry / "__init__.py").is_file():
                packages.append(entry.name)
        if not packages:
            return False, "no package under src/ (need src/<pkg>/__init__.py)"
        # Find the first package that carries a main.py; report success
        # there even if siblings are present. Reporting the path keeps
        # the output identical to what ``ajolopy dev`` would resolve.
        for pkg in sorted(packages):
            if (src_dir / pkg / "main.py").is_file():
                return True, f"src/{pkg}/main.py"
        return False, f"src/<pkg>/main.py not found (packages: {sorted(packages)!r})"


class EnvFilePresentCheck:
    """Check 6 — ``.env`` exists.

    Not finding a ``.env`` is a non-fatal warning (the project may
    legitimately drive every value through process env vars).
    """

    name = "env_file_present"

    def __init__(self, *, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self) -> tuple[bool | None, str]:
        if (self._cwd / ".env").is_file():
            return True, ".env"
        return None, ".env not found (using defaults)"


class EnvValidationCheck:
    """Check 7 — ``BaseConfig`` instantiates with no error.

    Prefers the project's own :class:`BaseConfig` subclass — same
    discovery walk ``env:show`` / ``env:validate`` use (see
    :func:`ajolopy.cli.commands.env._discover_config`). Falls back to
    the framework's bare ``BaseConfig`` when the project has not
    declared one yet.

    The fallback is intentionally lenient — instantiating the bare
    ``BaseConfig`` (``extra="forbid"``) against a ``.env`` populated
    with project-level keys would always fail and turn the doctor into
    a false-positive machine on every fresh install (AJ-94). Surfacing
    a "no project subclass" warning instead of a hard fail tells the
    user what is missing without misreporting their env-file shape.
    """

    name = "env_validation"

    def __init__(self, *, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self) -> tuple[bool | None, str]:
        try:
            from ajolopy.config import BaseConfig
        except ImportError as exc:  # pragma: no cover - defensive
            return False, f"could not import BaseConfig: {exc}"

        project_cls = self._discover_project_config(cwd=self._cwd)
        if project_cls is not None:
            try:
                project_cls()
            except Exception as exc:
                return (
                    False,
                    f"{project_cls.__name__}() raised {type(exc).__name__}: {exc}",
                )
            field_count = len(project_cls.model_fields)
            return True, f"{project_cls.__name__}: {field_count} fields OK"

        # No project subclass — instantiate the bare framework
        # BaseConfig only when the cwd's ``.env`` has zero entries the
        # bare class would reject. Otherwise surface a warning so the
        # user knows to declare a project-level subclass instead of
        # being told their env file is broken.
        if self._dotenv_has_keys(cwd=self._cwd):
            return (
                None,
                "no project BaseConfig subclass; declare one in src/<pkg>/config.py "
                "so doctor can validate the .env shape.",
            )
        try:
            config = BaseConfig()
        except Exception as exc:
            return False, f"BaseConfig() raised {type(exc).__name__}: {exc}"
        # ``BaseConfig`` has no declared fields; success here just means
        # the env files parsed cleanly. Surface the count of *process*
        # env vars to give the user a useful number when the project
        # defines no ``BaseConfig`` subclass yet.
        del config
        env_var_count = len(os.environ)
        return True, f"{env_var_count} vars OK"

    @staticmethod
    def _discover_project_config(*, cwd: Path) -> type[BaseConfig] | None:
        """Return the project's :class:`BaseConfig` subclass or ``None``.

        Wraps :func:`ajolopy.cli.commands.env._discover_config` so the
        doctor stays decoupled from its sibling subcommand. The helper
        is imported lazily so a circular-import or partial install
        cannot break the doctor's other checks; on any failure the
        check falls through to the framework-level bare ``BaseConfig``.
        """
        try:
            # ``_discover_config`` is private to the env subcommand but
            # shared deliberately as the canonical project-config walk —
            # the alternative is duplicating the ``src/<pkg>/app_module``
            # introspection in this module, which guarantees the two
            # implementations drift over time.
            from ajolopy.cli.commands.env import (
                _discover_config as discover,  # pyright: ignore[reportPrivateUsage]
            )
        except ImportError:  # pragma: no cover - defensive
            return None
        # The discovery helper writes "no BaseConfig subclass" diagnostics
        # to a stderr stream when missing. The doctor renders its own
        # diagnostics, so drop those messages into an in-memory buffer
        # so they never leak into the doctor's report.
        import io

        sink = io.StringIO()
        return discover(cwd=cwd, stderr=sink)

    @staticmethod
    def _dotenv_has_keys(*, cwd: Path) -> bool:
        """Return ``True`` when ``cwd/.env`` declares at least one entry.

        Uses the same lenient parser shape ``env:show`` / ``env:diff``
        rely on so a malformed line cannot crash the doctor.
        """
        env_path = cwd / ".env"
        if not env_path.is_file():
            return False
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[len("export ") :].lstrip()
            if "=" in stripped:
                return True
        return False


class ProviderHealthCheck:
    """Checks 8-10 -- provider API key is set AND ``health_check()`` works.

    The class is parameterised so the three provider checks share one
    implementation:

    - ``name``         — the spec's check name (``anthropic_api_key`` /
      ``openai_api_key`` / ``gemini_api_key``).
    - ``env_var``      — the API-key env var the provider reads.
    - ``module_path``  — dotted path to the provider package; imported
      lazily so a non-installed extra never breaks the doctor.
    - ``class_name``   — provider class to instantiate inside the module.

    Outcome rules:

    - Key missing → ``skip`` (the user has not opted into the provider).
    - Key set, instantiation fails → ``fail``.
    - Key set, health_check passes within 5s → ``pass``.
    - Key set, health_check raises or times out → ``warn`` (network /
      credentials problem — actionable but not a structural failure of
      the project; CI runs without API keys must not fail because the
      provider's status page is down).
    """

    def __init__(
        self,
        *,
        name: str,
        env_var: str,
        module_path: str,
        class_name: str,
    ) -> None:
        self.name = name
        self._env_var = env_var
        self._module_path = module_path
        self._class_name = class_name

    async def run(self) -> tuple[bool | None, str]:
        if not os.environ.get(self._env_var):
            return None, "skipped (not configured)"
        try:
            module = importlib.import_module(self._module_path)
        except ImportError as exc:
            return None, f"skipped ({self._module_path} not importable: {exc})"
        provider_cls = getattr(module, self._class_name, None)
        if provider_cls is None:
            return False, f"{self._class_name} not found in {self._module_path}"
        try:
            provider = cast("object", provider_cls())
        except Exception as exc:
            return False, f"could not construct {self._class_name}: {exc}"
        health_check = getattr(provider, "health_check", None)
        if health_check is None or not callable(health_check):
            return None, f"{self._class_name}.health_check() not implemented"
        try:
            # Unquoted form so CodeQL sees Awaitable used at runtime
            # (its `py/unused-import` rule misses string-form casts).
            awaitable = cast(Awaitable[None], health_check())  # noqa: TC006
            await asyncio.wait_for(awaitable, timeout=_NETWORK_TIMEOUT_S)
        except TimeoutError:
            return None, f"health_check timed out after {int(_NETWORK_TIMEOUT_S)}s"
        except Exception as exc:
            return None, f"health_check failed: {exc}"
        return True, "reachable"


class OtelEndpointCheck:
    """Check 11 — ``OTEL_EXPORTER_OTLP_ENDPOINT`` reachable when set.

    The probe is a short TCP connect — enough to validate the endpoint
    accepts connections without forcing the user to install the OTLP
    exporter SDK extra. Missing endpoint = warning (OTel is opt-in).
    """

    name = "otel_endpoint"

    async def run(self) -> tuple[bool | None, str]:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            return None, "OTEL_EXPORTER_OTLP_ENDPOINT not set"
        host, port = _parse_otel_endpoint(endpoint)
        if host is None:
            return None, f"OTEL endpoint {endpoint!r} could not be parsed"
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None,
                    _probe_tcp,
                    host,
                    port,
                ),
                timeout=_NETWORK_TIMEOUT_S,
            )
        except TimeoutError:
            return None, f"{endpoint} unreachable (timeout after {int(_NETWORK_TIMEOUT_S)}s)"
        except OSError as exc:
            return None, f"{endpoint} unreachable: {exc}"
        return True, f"{endpoint} reachable"


class MCPServersCheck:
    """Check 12 — every ``@MCP``-decorated class connects within 5s.

    Walks the process-wide :class:`MCPRegistry` (the decorator stamps
    classes into it at import time). For each registered class the
    check tries :meth:`MCPRegistry.connect_all_for(cls)` with a 5s
    timeout. Failures degrade to warnings — the doctor is a probe, not
    a gate. Skip when no classes have been registered.
    """

    name = "mcp_servers"

    async def run(self) -> tuple[bool | None, str]:
        try:
            from ajolopy.mcp.registry import get_mcp_registry
        except ImportError as exc:  # pragma: no cover - defensive
            return None, f"mcp registry not importable: {exc}"
        registry = get_mcp_registry()
        classes = registry.registered_classes()
        if not classes:
            return None, "skipped (no @MCP classes detected)"
        failures: list[str] = []
        for cls in classes:
            try:
                await asyncio.wait_for(
                    registry.connect_all_for(cls),
                    timeout=_NETWORK_TIMEOUT_S,
                )
            except TimeoutError:
                failures.append(f"{cls.__name__}: timeout")
            except Exception as exc:
                failures.append(f"{cls.__name__}: {exc}")
        if failures:
            return None, "; ".join(failures)
        return True, f"{len(classes)} @MCP class(es) reachable"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_otel_endpoint(endpoint: str) -> tuple[str | None, int]:
    """Pull ``(host, port)`` out of an OTLP endpoint string.

    OTLP endpoints come in two flavours: ``http(s)://host:port[/path]``
    (HTTP exporter) and bare ``host:port`` (gRPC exporter, less common
    in tooling). The parser accepts both. Returns ``(None, 0)`` when
    the input is unrecognisable so the caller can surface a clean
    warning instead of crashing.
    """
    text = endpoint.strip()
    if not text:
        return None, 0
    if "://" in text:
        parsed = urllib.parse.urlparse(text)
        if not parsed.hostname:
            return None, 0
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        return parsed.hostname, port
    # Bare ``host:port`` — split on the last colon to keep IPv6 happy
    # even though we are not formally claiming IPv6 support here.
    if ":" in text:
        host, _, port_str = text.rpartition(":")
        if not host:
            return None, 0
        try:
            return host, int(port_str)
        except ValueError:
            return None, 0
    return text, 80


def _probe_tcp(host: str, port: int) -> None:
    """Open a short TCP connection to ``host:port`` and close it.

    Raises :class:`OSError` on any socket error. The caller wraps this
    in :func:`asyncio.wait_for` for the per-check timeout.
    """
    with socket.create_connection((host, port), timeout=_NETWORK_TIMEOUT_S):
        # Connection established is enough — context manager closes it.
        pass


def _is_tty(stream: IO[str]) -> bool:
    """``True`` when ``stream`` is a real TTY.

    :class:`io.StringIO` raises :class:`io.UnsupportedOperation` from
    :meth:`fileno`. We treat any failure as "not a TTY" so the test
    buffer path renders plain ASCII.
    """
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError, ValueError:
        return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _RunReport:
    """Aggregated outcome of a full ``doctor`` run."""

    results: tuple[CheckResult, ...]
    passed: int
    failed: int
    warnings: int
    skipped: int

    @property
    def exit_code(self) -> int:
        return EXIT_FAIL if self.failed > 0 else EXIT_OK


_DEFAULT_CHECK_NAMES: tuple[str, ...] = (
    "python_version",
    "ajolopy_installed",
    "venv_present",
    "pyproject_present",
    "project_structure",
    "env_file_present",
    "env_validation",
    "anthropic_api_key",
    "openai_api_key",
    "gemini_api_key",
    "otel_endpoint",
    "mcp_servers",
)


def _build_checks(*, cwd: Path) -> list[Check]:
    """Return the 12 checks in their canonical order."""
    return [
        PythonVersionCheck(),
        AjolopyInstalledCheck(),
        VenvPresentCheck(cwd=cwd),
        PyprojectPresentCheck(cwd=cwd),
        ProjectStructureCheck(cwd=cwd),
        EnvFilePresentCheck(cwd=cwd),
        EnvValidationCheck(cwd=cwd),
        ProviderHealthCheck(
            name="anthropic_api_key",
            env_var="ANTHROPIC_API_KEY",
            module_path="ajolopy.providers.anthropic",
            class_name="AnthropicProvider",
        ),
        ProviderHealthCheck(
            name="openai_api_key",
            env_var="OPENAI_API_KEY",
            module_path="ajolopy.providers.openai",
            class_name="OpenAIProvider",
        ),
        ProviderHealthCheck(
            name="gemini_api_key",
            env_var="GEMINI_API_KEY",
            module_path="ajolopy.providers.gemini",
            class_name="GeminiProvider",
        ),
        OtelEndpointCheck(),
        MCPServersCheck(),
    ]


async def _run_checks(
    checks: Sequence[Check],
    *,
    skip: frozenset[str],
) -> _RunReport:
    """Execute every check, honour ``skip``, collect the results."""
    results: list[CheckResult] = []
    passed = failed = warnings = skipped = 0
    for check in checks:
        if check.name in skip:
            results.append(
                CheckResult(
                    name=check.name,
                    passed=None,
                    status="skip",
                    message="skipped (via --skip)",
                    duration_ms=0.0,
                )
            )
            skipped += 1
            continue
        started = time.perf_counter()
        try:
            outcome, message = await check.run()
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000.0
            results.append(
                CheckResult(
                    name=check.name,
                    passed=False,
                    status="fail",
                    message=f"check raised {type(exc).__name__}: {exc}",
                    duration_ms=duration_ms,
                )
            )
            failed += 1
            continue
        duration_ms = (time.perf_counter() - started) * 1000.0
        status: Status
        if outcome is True:
            status = "ok"
            passed += 1
        elif outcome is False:
            status = "fail"
            failed += 1
        else:
            # Tri-state ``None``: a skip is signalled by the message
            # starting with "skipped" so the renderer can tell them
            # apart from non-fatal warnings.
            if message.startswith("skipped"):
                status = "skip"
                skipped += 1
            else:
                status = "warn"
                warnings += 1
        results.append(
            CheckResult(
                name=check.name,
                passed=outcome,
                status=status,
                message=message,
                duration_ms=duration_ms,
            )
        )
    return _RunReport(
        results=tuple(results),
        passed=passed,
        failed=failed,
        warnings=warnings,
        skipped=skipped,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class _Glyphs:
    """Per-status glyph table for TTY vs ASCII fallback.

    Centralising the mapping makes it trivial to switch between emoji
    (real terminals) and plain ASCII (pytest's :class:`io.StringIO`
    capture) without sprinkling ``if use_emoji`` branches across the
    renderer.
    """

    EMOJI: ClassVar[dict[Status, str]] = {
        "ok": "✓",
        "fail": "✗",
        "warn": "⚠️ ",
        "skip": "-",
    }
    ASCII: ClassVar[dict[Status, str]] = {
        "ok": "[OK]",
        "fail": "[FAIL]",
        "warn": "[WARN]",
        "skip": "[SKIP]",
    }


def _render_tty(report: _RunReport, *, stdout: IO[str], use_emoji: bool) -> None:
    """Write the human-facing report to ``stdout``.

    ``use_emoji`` is split from the stream introspection so tests can
    drive both branches without monkeypatching :func:`os.isatty`.
    """
    glyphs = _Glyphs.EMOJI if use_emoji else _Glyphs.ASCII
    header_glyph = "\U0001f4cb" if use_emoji else ""
    header = (
        f"{header_glyph} Running {len(report.results)} diagnostic checks..."
        if header_glyph
        else f"Running {len(report.results)} diagnostic checks..."
    )
    print("", file=stdout)
    print(header, file=stdout)
    print("", file=stdout)

    name_width = max(len(r.name) for r in report.results) if report.results else 0
    for result in report.results:
        glyph = glyphs[result.status]
        print(f"{glyph} {result.name.ljust(name_width)}  {result.message}", file=stdout)

    print("", file=stdout)
    print(
        f"Summary: {report.passed} passed, {report.failed} failed, "
        f"{report.warnings} warnings, {report.skipped} skipped",
        file=stdout,
    )
    print("", file=stdout)
    print(f"Exit code: {report.exit_code}", file=stdout)


def _render_ci(report: _RunReport, *, stdout: IO[str]) -> None:
    """Write the JSON document defined in ``specs/cli-doctor.md``."""
    document = {
        "schema_version": _CI_SCHEMA_VERSION,
        "checks": [
            {
                "name": result.name,
                "passed": result.passed,
                "status": result.status,
                "message": result.message,
                "duration_ms": round(result.duration_ms, 3),
            }
            for result in report.results
        ],
        "passed": report.passed,
        "failed": report.failed,
        "warnings": report.warnings,
        "skipped": report.skipped,
        "exit_code": report.exit_code,
    }
    json.dump(document, stdout, indent=2, sort_keys=False)
    stdout.write("\n")


# ---------------------------------------------------------------------------
# argparse registration + dispatcher entry
# ---------------------------------------------------------------------------


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``doctor`` subparser to the dispatcher.

    ``_SubParsersAction`` is the documented type for argparse's
    subparser registry; the pyright ignore mirrors the convention used
    by every other ``ajolopy`` subcommand.
    """
    parser = sub.add_parser(
        "doctor",
        help="Run ~12 diagnostic checks against the current project + environment.",
        description=(
            "Run a fixed list of diagnostic checks in order and print a pass/fail "
            "report. Use --ci for JSON output and --skip <name> (repeatable) to skip "
            "individual checks."
        ),
    )
    parser.add_argument(
        "--ci",
        dest="ci",
        action="store_true",
        help="Emit a JSON document instead of the TTY-friendly report.",
    )
    parser.add_argument(
        "--skip",
        dest="skip",
        action="append",
        default=None,
        metavar="NAME",
        help=(f"Skip the named check; repeatable. Known names: {', '.join(_DEFAULT_CHECK_NAMES)}."),
    )
    parser.set_defaults(func=cmd_doctor)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Dispatcher entry — drives the doctor against real stdout/stderr."""
    return _command(args, stdout=sys.stdout, stderr=sys.stderr, cwd=Path.cwd())


def _command(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
    cwd: Path,
) -> int:
    """Build, run, render — split out so the test suite can drive it."""
    skip_arg = cast("list[str] | None", args.skip)
    skip = frozenset(skip_arg or ())
    unknown = skip - set(_DEFAULT_CHECK_NAMES)
    if unknown:
        print(
            f"ajolopy doctor: unknown --skip value(s) {sorted(unknown)!r}. "
            f"Known names: {list(_DEFAULT_CHECK_NAMES)!r}.",
            file=stderr,
        )
        return EXIT_FAIL
    checks = _build_checks(cwd=cwd)
    report = asyncio.run(_run_checks(checks, skip=skip))
    if bool(args.ci):
        _render_ci(report, stdout=stdout)
    else:
        _render_tty(report, stdout=stdout, use_emoji=_is_tty(stdout))
    return report.exit_code
