"""Tests for :class:`ajolopy.cli.deploy.docker.DockerTarget`."""

from pathlib import Path

import pytest

from ajolopy.cli.deploy import DeployContext
from ajolopy.cli.deploy.docker import DockerTarget
from ajolopy.templates.docker import render_dockerfile, render_dockerignore


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


@pytest.fixture
def target() -> DockerTarget:
    return DockerTarget()


def test_prepare_emits_dockerfile_and_dockerignore(target: DockerTarget, tmp_path: Path) -> None:
    result = target.prepare(_ctx(tmp_path))
    assert set(result.files) == {Path("Dockerfile.prod"), Path(".dockerignore")}


def test_dockerfile_matches_renderer_output(target: DockerTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, port=8080)
    expected = render_dockerfile(
        python_version=ctx.python_version,
        app_module=ctx.app_module,
        port=ctx.port,
    )
    result = target.prepare(ctx)
    assert result.files[Path("Dockerfile.prod")] == expected


def test_dockerignore_matches_renderer_output(target: DockerTarget, tmp_path: Path) -> None:
    expected = render_dockerignore()
    result = target.prepare(_ctx(tmp_path))
    assert result.files[Path(".dockerignore")] == expected


def test_next_steps_uses_project_name(target: DockerTarget, tmp_path: Path) -> None:
    steps = list(
        target.next_steps(_ctx(tmp_path, project_name="my-app"), target.prepare(_ctx(tmp_path)))
    )
    assert steps[0] == "docker build -f Dockerfile.prod -t my-app:latest ."
    assert steps[1] == "docker run -p 3000:3000 --env-file .env my-app:latest"


def test_next_steps_uses_context_port(target: DockerTarget, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, port=9000, project_name="svc")
    steps = list(target.next_steps(ctx, target.prepare(ctx)))
    assert steps[1] == "docker run -p 9000:9000 --env-file .env svc:latest"


def test_name_and_description_are_stable(target: DockerTarget) -> None:
    assert target.name == "docker"
    assert "Dockerfile" in target.description
