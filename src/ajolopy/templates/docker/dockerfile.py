"""Multi-stage ``Dockerfile`` text renderer.

The template mirrors ``07 - Deploy y Docker`` exactly: three stages
(``deps`` / ``development`` / ``production``) sharing a ``python:<v>-slim``
base, ``uv`` for dependency installation, a non-root prod user, and a
``HEALTHCHECK`` that curls ``/health``.

Pure function: no I/O, no template engine. The caller decides where to
write the bytes. Output is deterministic — same kwargs always produce
the same string, so snapshot tests can pin the output bit-for-bit.
"""

import re

# A Python version is accepted as either a bare ``X.Y`` (e.g. ``3.14``)
# or a tag suffix already containing ``-slim`` (e.g. ``3.14-slim``). Any
# other shape — empty string, single integer, alphabetic suffixes — is
# a user error and raises ``ValueError``.
_VERSION_RE = re.compile(r"^(?P<num>\d+\.\d+)(?:-slim)?$")

# Lowest / highest valid TCP ports. ``0`` is reserved (kernel-assigned)
# and rejected because emitting ``EXPOSE 0`` makes no sense in a
# Dockerfile.
_MIN_PORT = 1
_MAX_PORT = 65535


def _normalise_python_version(version: str) -> str:
    """Return the bare ``X.Y`` form of ``version`` (strip a trailing
    ``-slim`` suffix if the caller passed one).

    Raises ``ValueError`` with a message naming the expected ``X.Y``
    format when the input does not match the regex.
    """

    match = _VERSION_RE.match(version)
    if match is None:
        raise ValueError(
            f"python_version={version!r} is not valid; expected 'X.Y' (e.g. '3.14') or 'X.Y-slim'",
        )
    return match.group("num")


def _validate_port(port: int, *, name: str) -> None:
    if port < _MIN_PORT or port > _MAX_PORT:
        raise ValueError(
            f"{name}={port} is out of range; expected {_MIN_PORT}..{_MAX_PORT}",
        )


def _validate_workers(workers: int) -> None:
    if workers < 1:
        raise ValueError(f"workers={workers} must be >= 1")


def render_dockerfile(
    *,
    python_version: str = "3.14",
    app_module: str = "main:app",
    port: int = 3000,
    workers: int = 4,
) -> str:
    """Render the canonical multi-stage ``Dockerfile`` as a string.

    Args:
        python_version: ``X.Y`` Python version. ``-slim`` suffix is
            accepted and stripped. Default ``3.14``.
        app_module: Uvicorn ASGI target in ``<module>:<callable>`` form.
        port: TCP port exposed and curled by the healthcheck.
        workers: Production ``uvicorn --workers`` count.

    The output always opens with ``# syntax=docker/dockerfile:1.7`` so
    BuildKit cache mounts are available to downstream extenders.
    """

    py = _normalise_python_version(python_version)
    _validate_port(port, name="port")
    _validate_workers(workers)

    base_image = f"python:{py}-slim"

    return (
        # syntax directive must be the very first line for BuildKit to
        # honour the version pin.
        "# syntax=docker/dockerfile:1.7\n"
        "\n"
        "# ──────────────────────────────────────────────────────────────\n"
        "# Stage 1: dependencies\n"
        "# ──────────────────────────────────────────────────────────────\n"
        f"FROM {base_image} AS deps\n"
        "WORKDIR /app\n"
        "\n"
        "# Install uv (the fastest Python package manager).\n"
        "RUN pip install --no-cache-dir uv\n"
        "\n"
        "# Copy only dependency manifests so this layer caches well.\n"
        "COPY pyproject.toml uv.lock* ./\n"
        "RUN uv sync --frozen --no-dev\n"
        "\n"
        "# ──────────────────────────────────────────────────────────────\n"
        "# Stage 2: development (hot reload)\n"
        "# ──────────────────────────────────────────────────────────────\n"
        "FROM deps AS development\n"
        "\n"
        "# Re-install with dev dependencies for tests + tooling.\n"
        "RUN uv sync --frozen\n"
        "COPY . .\n"
        "\n"
        f"EXPOSE {port}\n"
        f'CMD ["uvicorn", "{app_module}", "--host", "0.0.0.0", '
        f'"--port", "{port}", "--reload"]\n'
        "\n"
        "# ──────────────────────────────────────────────────────────────\n"
        "# Stage 3: production (slim, non-root, healthcheck)\n"
        "# ──────────────────────────────────────────────────────────────\n"
        "FROM deps AS production\n"
        "\n"
        "COPY . .\n"
        "\n"
        "# Non-root user (required by k8s PSA/PSP and a general best practice).\n"
        "RUN useradd -m appuser && chown -R appuser /app\n"
        "USER appuser\n"
        "\n"
        f"EXPOSE {port}\n"
        "\n"
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\\n"
        f"  CMD curl -f http://localhost:{port}/health || exit 1\n"
        "\n"
        # --no-access-log: access logging is emitted via OpenTelemetry
        # (richer than stdlib). --workers default 4 per doc 07.
        f'CMD ["uvicorn", "{app_module}", "--host", "0.0.0.0", '
        f'"--port", "{port}", '
        f'"--workers", "{workers}", "--no-access-log"]\n'
    )
