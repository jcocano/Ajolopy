"""Tests for the Fly.io deploy target (AJ-42).

The target is pure: ``prepare`` returns a single in-memory file and
``next_steps`` yields five static commands. Tests parse the rendered
TOML with stdlib ``tomllib`` to assert structure rather than matching
bytes — that keeps the suite tolerant of harmless formatting tweaks.
"""

import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from ajolopy.cli.deploy import DeployContext
from ajolopy.cli.deploy.fly import FlyTarget


def _ctx(
    project_root: Path,
    *,
    project_name: str = "acme",
    port: int = 3000,
) -> DeployContext:
    return DeployContext(
        project_root=project_root,
        app_module="main:app",
        port=port,
        python_version="3.14",
        project_name=project_name,
        is_tty=False,
        yes=False,
        dry_run=False,
        force=False,
    )


# ---------------------------------------------------------------------------
# Class-level metadata
# ---------------------------------------------------------------------------


def test_name_is_fly() -> None:
    assert FlyTarget.name == "fly"


# ---------------------------------------------------------------------------
# prepare — emitted files
# ---------------------------------------------------------------------------


def test_prepare_returns_single_fly_toml(tmp_path: Path) -> None:
    result = FlyTarget().prepare(_ctx(tmp_path))
    assert list(result.files.keys()) == [Path("fly.toml")]
    assert result.files[Path("fly.toml")] != ""


def test_prepare_emits_no_notes(tmp_path: Path) -> None:
    result = FlyTarget().prepare(_ctx(tmp_path))
    assert result.notes == ()


# ---------------------------------------------------------------------------
# Rendered TOML structure
# ---------------------------------------------------------------------------


def _parse(result_body: str) -> dict[str, Any]:
    return tomllib.loads(result_body)


def test_rendered_toml_parses(tmp_path: Path) -> None:
    body = FlyTarget().prepare(_ctx(tmp_path)).files[Path("fly.toml")]
    # tomllib.loads must not raise.
    _parse(body)


def test_top_level_fields(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, project_name="neon-svc")
    parsed = _parse(FlyTarget().prepare(ctx).files[Path("fly.toml")])
    assert parsed["app"] == "neon-svc"
    assert parsed["primary_region"] == "iad"


def test_build_section_uses_dockerfile(tmp_path: Path) -> None:
    parsed = _parse(FlyTarget().prepare(_ctx(tmp_path)).files[Path("fly.toml")])
    build = cast("dict[str, Any]", parsed["build"])
    assert build["dockerfile"] == "Dockerfile"


def test_env_sets_app_env_production(tmp_path: Path) -> None:
    parsed = _parse(FlyTarget().prepare(_ctx(tmp_path)).files[Path("fly.toml")])
    env = cast("dict[str, Any]", parsed["env"])
    assert env["APP_ENV"] == "production"


def test_service_internal_port_matches_ctx(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, port=8080)
    parsed = _parse(FlyTarget().prepare(ctx).files[Path("fly.toml")])
    services = cast("list[dict[str, Any]]", parsed["services"])
    assert len(services) == 1
    assert services[0]["internal_port"] == 8080
    assert services[0]["protocol"] == "tcp"


def test_service_exposes_ports_80_and_443(tmp_path: Path) -> None:
    parsed = _parse(FlyTarget().prepare(_ctx(tmp_path)).files[Path("fly.toml")])
    ports = cast(
        "list[dict[str, Any]]",
        cast("list[dict[str, Any]]", parsed["services"])[0]["ports"],
    )
    by_port = {p["port"]: p for p in ports}
    assert 80 in by_port
    assert by_port[80]["handlers"] == ["http"]
    assert by_port[80]["force_https"] is True
    assert 443 in by_port
    assert by_port[443]["handlers"] == ["tls", "http"]


def test_service_concurrency(tmp_path: Path) -> None:
    parsed = _parse(FlyTarget().prepare(_ctx(tmp_path)).files[Path("fly.toml")])
    concurrency = cast(
        "dict[str, Any]",
        cast("list[dict[str, Any]]", parsed["services"])[0]["concurrency"],
    )
    assert concurrency["type"] == "connections"
    assert concurrency["hard_limit"] == 50
    assert concurrency["soft_limit"] == 25


def test_health_check(tmp_path: Path) -> None:
    parsed = _parse(FlyTarget().prepare(_ctx(tmp_path)).files[Path("fly.toml")])
    checks = cast("dict[str, Any]", parsed["checks"])
    health = cast("dict[str, Any]", checks["health"])
    assert health["type"] == "http"
    assert health["interval"] == "30s"
    assert health["timeout"] == "5s"
    assert health["grace_period"] == "30s"
    assert health["method"] == "get"
    assert health["path"] == "/health"


# ---------------------------------------------------------------------------
# next_steps — the Fly.io deploy flow
# ---------------------------------------------------------------------------


_EXPECTED_NEXT_STEPS = (
    "fly auth login",
    "fly secrets set ANTHROPIC_API_KEY=sk-ant-...",
    "fly secrets set DATABASE_URL=postgresql://...",
    "fly launch",
    "fly deploy",
)


def test_next_steps_yields_five_commands_in_order(tmp_path: Path) -> None:
    target = FlyTarget()
    ctx = _ctx(tmp_path)
    result = target.prepare(ctx)
    steps = list(target.next_steps(ctx, result))
    assert steps == list(_EXPECTED_NEXT_STEPS)


@pytest.mark.parametrize("idx", list(range(len(_EXPECTED_NEXT_STEPS))))
def test_next_step_at_index(tmp_path: Path, idx: int) -> None:
    target = FlyTarget()
    ctx = _ctx(tmp_path)
    steps = list(target.next_steps(ctx, target.prepare(ctx)))
    assert steps[idx] == _EXPECTED_NEXT_STEPS[idx]
