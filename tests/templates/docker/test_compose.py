"""Tests for ``render_docker_compose``.

Tests parse the rendered output with ``yaml.safe_load`` and assert on
the structural result rather than the raw string. The snapshot tests
pin the wire format separately so the indentation / comment placement
is also reviewable.
"""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from ajolopy.templates.docker import render_docker_compose


def _load(rendered: str) -> dict[str, Any]:
    """Parse the rendered compose body via PyYAML.

    PyYAML strips comments on load, so this is a structural view —
    snapshot tests cover the comments.
    """

    return cast("dict[str, Any]", yaml.safe_load(rendered))


class TestNoDatabases:
    def test_top_level_has_only_services(self) -> None:
        data = _load(render_docker_compose())
        assert set(data.keys()) == {"services"}

    def test_app_service_has_no_depends_on(self) -> None:
        data = _load(render_docker_compose())
        app = data["services"]["app"]
        assert "depends_on" not in app

    def test_app_service_keeps_bind_mount_in_development(self) -> None:
        data = _load(render_docker_compose())
        app = data["services"]["app"]
        assert app["volumes"] == ["./:/app"]


class TestPostgres:
    def test_adds_db_service_with_alpine_image(self) -> None:
        data = _load(render_docker_compose(databases=("postgres",)))
        db = data["services"]["db"]
        assert db["image"] == "postgres:16-alpine"

    def test_uses_pg_isready_healthcheck(self) -> None:
        data = _load(render_docker_compose(databases=("postgres",)))
        healthcheck = data["services"]["db"]["healthcheck"]
        assert healthcheck["test"] == ["CMD-SHELL", "pg_isready -U ${DB_USER}"]

    def test_app_depends_on_db_service_healthy(self) -> None:
        data = _load(render_docker_compose(databases=("postgres",)))
        depends_on = data["services"]["app"]["depends_on"]
        assert depends_on == {"db": {"condition": "service_healthy"}}

    def test_top_level_volumes_has_pgdata(self) -> None:
        data = _load(render_docker_compose(databases=("postgres",)))
        assert "volumes" in data
        assert "pgdata" in data["volumes"]


class TestPgvector:
    def test_swaps_image_to_pgvector(self) -> None:
        data = _load(render_docker_compose(databases=("pgvector",)))
        db = data["services"]["db"]
        assert db["image"] == "pgvector/pgvector:pg16"

    def test_keeps_pg_isready_healthcheck(self) -> None:
        data = _load(render_docker_compose(databases=("pgvector",)))
        healthcheck = data["services"]["db"]["healthcheck"]
        assert healthcheck["test"] == ["CMD-SHELL", "pg_isready -U ${DB_USER}"]

    def test_keeps_pgdata_volume(self) -> None:
        data = _load(render_docker_compose(databases=("pgvector",)))
        assert data["volumes"] == {"pgdata": None}


class TestPostgresPgvectorMutualExclusion:
    def test_both_together_raises(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            render_docker_compose(databases=("postgres", "pgvector"))

    def test_reverse_order_also_raises(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            render_docker_compose(databases=("pgvector", "postgres"))


class TestRedis:
    def test_adds_redis_service_with_alpine_image(self) -> None:
        data = _load(render_docker_compose(databases=("redis",)))
        redis = data["services"]["redis"]
        assert redis["image"] == "redis:7-alpine"

    def test_uses_redis_cli_ping_healthcheck(self) -> None:
        data = _load(render_docker_compose(databases=("redis",)))
        healthcheck = data["services"]["redis"]["healthcheck"]
        assert healthcheck["test"] == ["CMD", "redis-cli", "ping"]

    def test_app_depends_on_redis_service_healthy(self) -> None:
        data = _load(render_docker_compose(databases=("redis",)))
        depends_on = data["services"]["app"]["depends_on"]
        assert depends_on == {"redis": {"condition": "service_healthy"}}

    def test_redis_alone_emits_no_volumes_block(self) -> None:
        # Redis ships its data in-process for the default dev image, no
        # named volume needed.
        data = _load(render_docker_compose(databases=("redis",)))
        assert "volumes" not in data


class TestQdrant:
    def test_adds_qdrant_service(self) -> None:
        data = _load(render_docker_compose(databases=("qdrant",)))
        qdrant = data["services"]["qdrant"]
        assert qdrant["image"] == "qdrant/qdrant:latest"

    def test_owns_qdrantdata_volume(self) -> None:
        data = _load(render_docker_compose(databases=("qdrant",)))
        assert data["volumes"] == {"qdrantdata": None}

    def test_app_does_not_depend_on_qdrant(self) -> None:
        # Qdrant has no native healthcheck, so depends_on with
        # condition: service_healthy would deadlock startup.
        data = _load(render_docker_compose(databases=("qdrant",)))
        assert "depends_on" not in data["services"]["app"]

    def test_emits_todo_healthcheck_comment_above_service(self) -> None:
        # PyYAML strips comments on load, so assert against the raw
        # text. The comment must appear immediately above the qdrant
        # service entry to give users a chance to spot the gap.
        rendered = render_docker_compose(databases=("qdrant",))
        lines = rendered.splitlines()
        qdrant_index = lines.index("  qdrant:")
        assert lines[qdrant_index - 1] == (
            "  # TODO: healthcheck — qdrant ships no native healthcheck endpoint"
        )


class TestAllDatabasesCombined:
    def test_postgres_redis_qdrant_emits_all_services_in_order(self) -> None:
        data = _load(render_docker_compose(databases=("postgres", "redis", "qdrant")))
        # Service order in the rendered text follows the input tuple.
        # PyYAML preserves insertion order in Python 3.7+.
        keys = list(data["services"].keys())
        assert keys == ["app", "db", "redis", "qdrant"]

    def test_all_three_emits_pgdata_and_qdrantdata_volumes(self) -> None:
        data = _load(render_docker_compose(databases=("postgres", "redis", "qdrant")))
        assert set(data["volumes"].keys()) == {"pgdata", "qdrantdata"}

    def test_depends_on_includes_only_healthy_services(self) -> None:
        data = _load(render_docker_compose(databases=("postgres", "redis", "qdrant")))
        depends_on = data["services"]["app"]["depends_on"]
        # qdrant is intentionally excluded — no native healthcheck.
        assert set(depends_on.keys()) == {"db", "redis"}
        for entry in depends_on.values():
            assert entry == {"condition": "service_healthy"}


class TestTarget:
    def test_production_drops_bind_mount(self) -> None:
        data = _load(render_docker_compose(target="production"))
        app = data["services"]["app"]
        assert "volumes" not in app

    def test_production_sets_build_target(self) -> None:
        data = _load(render_docker_compose(target="production"))
        assert data["services"]["app"]["build"]["target"] == "production"

    def test_development_default_target(self) -> None:
        data = _load(render_docker_compose())
        assert data["services"]["app"]["build"]["target"] == "development"


class TestStructure:
    def test_no_databases_top_level(self) -> None:
        # Top-level keys when there is no stateful service should be
        # exactly {"services"} — no empty volumes mapping.
        data = _load(render_docker_compose())
        assert set(data.keys()) == {"services"}

    def test_with_volumes_top_level(self) -> None:
        data = _load(render_docker_compose(databases=("postgres",)))
        assert set(data.keys()) == {"services", "volumes"}

    def test_app_port_propagates_to_ports_mapping(self) -> None:
        data = _load(render_docker_compose(app_port=4000))
        ports = data["services"]["app"]["ports"]
        assert ports == ["4000:4000"]

    @pytest.mark.parametrize("bad_port", [0, -1, 65536])
    def test_invalid_app_port_raises(self, bad_port: int) -> None:
        with pytest.raises(ValueError, match="app_port="):
            render_docker_compose(app_port=bad_port)

    def test_deterministic(self) -> None:
        a = render_docker_compose(databases=("postgres", "redis"))
        b = render_docker_compose(databases=("postgres", "redis"))
        assert a == b


class TestSnapshots:
    def test_no_databases_matches_snapshot(self) -> None:
        snapshot = Path(__file__).parent / "__snapshots__" / "compose_no_databases.txt"
        assert render_docker_compose() == snapshot.read_text()

    def test_postgres_redis_qdrant_matches_snapshot(self) -> None:
        snapshot = Path(__file__).parent / "__snapshots__" / "compose_postgres_redis_qdrant.txt"
        assert (
            render_docker_compose(databases=("postgres", "redis", "qdrant")) == snapshot.read_text()
        )
