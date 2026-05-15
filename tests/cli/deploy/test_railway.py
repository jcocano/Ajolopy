"""Tests for :class:`ajolopy.cli.deploy.railway.RailwayTarget`."""

import json
from pathlib import Path

import pytest

from ajolopy.cli.deploy import DeployContext
from ajolopy.cli.deploy.railway import RailwayTarget


def _ctx(project_root: Path, *, app_module: str = "main:app") -> DeployContext:
    return DeployContext(
        project_root=project_root,
        app_module=app_module,
        port=3000,
        python_version="3.14",
        project_name="acme",
        is_tty=False,
        yes=False,
        dry_run=False,
        force=False,
    )


@pytest.fixture
def target() -> RailwayTarget:
    return RailwayTarget()


def test_name_and_description(target: RailwayTarget) -> None:
    assert target.name == "railway"
    assert "Railway" in target.description


def test_prepare_emits_single_manifest(target: RailwayTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    assert set(result.files) == {Path("railway.json")}
    assert result.files[Path("railway.json")]


def test_manifest_is_valid_json(target: RailwayTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    contents = result.files[Path("railway.json")]
    # Parsing must succeed and yield a mapping.
    parsed = json.loads(contents)
    assert isinstance(parsed, dict)


def test_manifest_top_level_keys(target: RailwayTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    parsed = json.loads(result.files[Path("railway.json")])
    assert set(parsed.keys()) == {"$schema", "build", "deploy"}
    assert parsed["$schema"] == "https://railway.app/railway.schema.json"


def test_manifest_build_block(target: RailwayTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    parsed = json.loads(result.files[Path("railway.json")])
    build = parsed["build"]
    assert build["builder"] == "DOCKERFILE"
    assert build["dockerfilePath"] == "Dockerfile"
    assert build["buildTarget"] == "production"


def test_manifest_deploy_block(target: RailwayTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path, app_module="neon_svc.main:app"))
    parsed = json.loads(result.files[Path("railway.json")])
    deploy = parsed["deploy"]
    # The start command interpolates the context's app_module and keeps
    # the literal ``$PORT`` placeholder that Railway expands at deploy time.
    assert "neon_svc.main:app" in deploy["startCommand"]
    assert "$PORT" in deploy["startCommand"]
    assert deploy["healthcheckPath"] == "/health"
    assert deploy["healthcheckTimeout"] == 30
    assert deploy["restartPolicyType"] == "ON_FAILURE"
    assert deploy["restartPolicyMaxRetries"] == 3


def test_manifest_uses_default_app_module(target: RailwayTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    parsed = json.loads(result.files[Path("railway.json")])
    assert "main:app" in parsed["deploy"]["startCommand"]


def test_next_steps_order(target: RailwayTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = target.prepare(ctx)
    steps = list(target.next_steps(ctx, result))
    assert steps == ["railway login", "railway link", "railway up"]
