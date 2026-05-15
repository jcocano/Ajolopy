"""Tests for :class:`ajolopy.cli.deploy.render.RenderTarget`."""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from ajolopy.cli.deploy import DeployContext
from ajolopy.cli.deploy.render import RenderTarget


def _ctx(project_root: Path, *, project_name: str = "acme", port: int = 3000) -> DeployContext:
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


def _parse(body: str) -> dict[str, Any]:
    """Parse the rendered YAML and assert it is a top-level mapping."""
    loaded = yaml.safe_load(body)
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


@pytest.fixture
def target() -> RenderTarget:
    return RenderTarget()


def test_name_and_description_are_stable(target: RenderTarget) -> None:
    assert target.name == "render"
    assert "Render" in target.description


def test_prepare_emits_single_render_yaml(target: RenderTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    assert set(result.files) == {Path("render.yaml")}
    body = result.files[Path("render.yaml")]
    assert isinstance(body, str)
    assert body  # non-empty


def test_rendered_yaml_parses(target: RenderTarget, tmp_path: Path) -> None:
    body = target.prepare(_ctx(tmp_path)).files[Path("render.yaml")]
    data = _parse(body)
    assert "services" in data


def test_services_is_single_web_service(target: RenderTarget, tmp_path: Path) -> None:
    body = target.prepare(_ctx(tmp_path)).files[Path("render.yaml")]
    data = _parse(body)
    services = data["services"]
    assert isinstance(services, list)
    assert len(services) == 1


def test_service_fields_match_brief(target: RenderTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, project_name="neon-svc")
    body = target.prepare(ctx).files[Path("render.yaml")]
    data = _parse(body)
    service = cast("dict[str, Any]", data["services"][0])
    assert service["type"] == "web"
    assert service["name"] == "neon-svc"
    assert service["runtime"] == "docker"
    assert service["dockerfilePath"] == "./Dockerfile"
    assert service["dockerTarget"] == "production"
    assert service["plan"] == "starter"
    assert service["healthCheckPath"] == "/health"


def test_env_vars_pair_is_app_env_and_port(target: RenderTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, port=9000)
    body = target.prepare(ctx).files[Path("render.yaml")]
    data = _parse(body)
    service = cast("dict[str, Any]", data["services"][0])
    env_vars = service["envVars"]
    assert isinstance(env_vars, list)
    assert env_vars == [
        {"key": "APP_ENV", "value": "production"},
        {"key": "PORT", "value": 9000},
    ]


def test_next_steps_yields_two_strings(target: RenderTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    steps = list(target.next_steps(ctx, target.prepare(ctx)))
    assert steps == [
        "Commit and push the generated render.yaml to your repo.",
        "Visit https://dashboard.render.com/blueprints to apply the blueprint.",
    ]


def test_service_name_tracks_context_project_name(target: RenderTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, project_name="my-app")
    body = target.prepare(ctx).files[Path("render.yaml")]
    data = _parse(body)
    assert cast("dict[str, Any]", data["services"][0])["name"] == "my-app"


def test_port_default_three_thousand(target: RenderTarget, tmp_path: Path) -> None:
    body = target.prepare(_ctx(tmp_path)).files[Path("render.yaml")]
    data = _parse(body)
    env_vars = cast("dict[str, Any]", data["services"][0])["envVars"]
    port_entry = next(entry for entry in env_vars if entry["key"] == "PORT")
    assert port_entry["value"] == 3000
