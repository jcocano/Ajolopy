"""``docker-compose.yml`` text renderer.

Builds a development-oriented compose file by hand: the framework owns
the indentation, line ordering, and comment placement so the snapshot
tests can pin the output bit-for-bit. No external YAML serializer is
used at render time — PyYAML stays a dev-only dependency used by tests
to parse and assert on the generated structure.
"""

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

DatabaseChoice = Literal["postgres", "pgvector", "redis", "qdrant"]
Target = Literal["development", "production"]

# Database choices that ship a Postgres-flavoured image. They cannot
# coexist because both would map onto the same ``db`` service.
_POSTGRES_FLAVOURS: frozenset[DatabaseChoice] = frozenset({"postgres", "pgvector"})

# Service names that own a named Docker volume. Lookup is by the
# ``DatabaseChoice`` key; the value is the volume name emitted at the
# top level of the compose file.
_VOLUME_BY_DB: dict[DatabaseChoice, str] = {
    "postgres": "pgdata",
    "pgvector": "pgdata",
    "qdrant": "qdrantdata",
}

# Database choices that should appear as ``depends_on`` entries on the
# ``app`` service with ``condition: service_healthy`` (i.e. they expose
# a healthcheck the app should wait for). ``qdrant`` is intentionally
# omitted because its image has no native healthcheck — see the TODO
# comment emitted just above the qdrant service.
_HEALTHY_SERVICES: frozenset[DatabaseChoice] = frozenset({"postgres", "pgvector", "redis"})

# Per-database service body. Each renderer returns the lines for a
# single service (already indented at 2 spaces under ``services:``) plus
# an optional comment block immediately preceding the service entry.
# Keeping these here — instead of in a registry mapping — lets each
# renderer use a multiline f-string template that reads top-to-bottom.


def _render_postgres_service(*, image: str) -> str:
    return (
        "  db:\n"
        f"    image: {image}\n"
        "    environment:\n"
        "      POSTGRES_USER: ${DB_USER}\n"
        "      POSTGRES_PASSWORD: ${DB_PASS}\n"
        "      POSTGRES_DB: ${DB_NAME}\n"
        "    volumes:\n"
        "      - pgdata:/var/lib/postgresql/data\n"
        "    ports:\n"
        '      - "5432:5432"\n'
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]\n'
        "      interval: 5s\n"
        "      timeout: 3s\n"
        "      retries: 5\n"
    )


def _render_redis_service() -> str:
    return (
        "  redis:\n"
        "    image: redis:7-alpine\n"
        "    ports:\n"
        '      - "6379:6379"\n'
        "    healthcheck:\n"
        '      test: ["CMD", "redis-cli", "ping"]\n'
        "      interval: 5s\n"
    )


def _render_qdrant_service() -> str:
    # qdrant/qdrant:latest ships no native healthcheck. The TODO comment
    # is emitted on its own line above the service so users see the gap
    # the moment they open the compose file.
    return (
        "  # TODO: healthcheck — qdrant ships no native healthcheck endpoint\n"
        "  qdrant:\n"
        "    image: qdrant/qdrant:latest\n"
        "    ports:\n"
        '      - "6333:6333"\n'
        "    volumes:\n"
        "      - qdrantdata:/qdrant/storage\n"
    )


def _validate_databases(databases: Sequence[DatabaseChoice]) -> None:
    # Mutual exclusion: postgres and pgvector both target the ``db``
    # service, so allowing both would emit two services with the same
    # key — invalid compose.
    flavours_present = {db for db in databases if db in _POSTGRES_FLAVOURS}
    if len(flavours_present) > 1:
        raise ValueError(
            "databases=('postgres', 'pgvector') are mutually exclusive — "
            "pgvector already bundles Postgres, so the two would map to "
            "the same `db` service. Pick exactly one.",
        )

    # Duplicates would also produce duplicate service blocks.
    if len(set(databases)) != len(databases):
        raise ValueError(f"databases={tuple(databases)!r} contains duplicates")


def _validate_port(port: int, *, name: str) -> None:
    if port < 1 or port > 65535:
        raise ValueError(f"{name}={port} is out of range; expected 1..65535")


def _render_app_service(
    *,
    app_port: int,
    target: Target,
    databases: Sequence[DatabaseChoice],
) -> str:
    lines: list[str] = [
        "  app:\n",
        "    build:\n",
        "      context: .\n",
        f"      target: {target}\n",
    ]

    # The bind-mount is the hot-reload mechanism for development. It is
    # explicitly dropped in production target so the image's frozen
    # source tree is what gets executed (no surprise overlays).
    if target == "development":
        lines.extend(
            [
                "    volumes:\n",
                "      - ./:/app\n",
            ],
        )

    lines.extend(
        [
            "    ports:\n",
            f'      - "{app_port}:{app_port}"\n',
            "    env_file: .env\n",
        ],
    )

    # depends_on only emits for services that expose a healthcheck the
    # app should wait on. Order follows the user-supplied tuple so the
    # compose file is deterministic across runs (no hash-seed drift).
    healthy = [db for db in databases if db in _HEALTHY_SERVICES]
    if healthy:
        lines.append("    depends_on:\n")
        for db in healthy:
            service_name = "db" if db in _POSTGRES_FLAVOURS else db
            lines.append(f"      {service_name}:\n")
            lines.append("        condition: service_healthy\n")

    return "".join(lines)


def _render_db_service(db: DatabaseChoice) -> str:
    if db == "postgres":
        return _render_postgres_service(image="postgres:16-alpine")
    if db == "pgvector":
        return _render_postgres_service(image="pgvector/pgvector:pg16")
    if db == "redis":
        return _render_redis_service()
    # mypy/pyright narrow to ``Literal["qdrant"]`` here.
    return _render_qdrant_service()


def render_docker_compose(
    *,
    databases: Sequence[DatabaseChoice] = (),
    app_port: int = 3000,
    target: Target = "development",
) -> str:
    """Render a ``docker-compose.yml`` body as a string.

    Args:
        databases: Ordered tuple of database services to include. Order
            is preserved in the output. ``("postgres", "pgvector")``
            raises ``ValueError`` (mutually exclusive).
        app_port: Host + container port for the ``app`` service.
        target: ``Dockerfile`` stage to build. ``"development"`` adds
            the bind mount ``./:/app``; ``"production"`` drops it.

    Top-level structure:
        - ``services:`` is always emitted.
        - ``volumes:`` is only emitted when at least one stateful
          service (postgres / pgvector / qdrant) is selected.
    """

    _validate_databases(databases)
    _validate_port(app_port, name="app_port")

    parts: list[str] = ["services:\n"]
    parts.append(_render_app_service(app_port=app_port, target=target, databases=databases))
    for db in databases:
        parts.append(_render_db_service(db))

    # Volumes block: collect names in user order, dedup while preserving
    # insertion order. Empty -> skip the block entirely so the file is
    # not stuck with an empty `volumes:` mapping.
    volume_names: list[str] = []
    for db in databases:
        name = _VOLUME_BY_DB.get(db)
        if name is not None and name not in volume_names:
            volume_names.append(name)

    if volume_names:
        parts.append("\nvolumes:\n")
        for name in volume_names:
            parts.append(f"  {name}:\n")

    return "".join(parts)
