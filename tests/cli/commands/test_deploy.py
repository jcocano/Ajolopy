"""Tests for the ``ajolopy deploy`` CLI command driver.

The command writes real files into ``tmp_path``; nothing in this
suite invokes Docker, Fly, or any other platform CLI.
"""

import argparse
import io
from pathlib import Path
from typing import IO

import pytest

from ajolopy.cli.commands.deploy import (
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_USER_ABORT,
    _build_help_description,
    _command,
    register,
)


def _namespace(
    target: str,
    *,
    out_dir: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
    yes: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        target=target,
        out_dir=str(out_dir) if out_dir is not None else None,
        dry_run=dry_run,
        force=force,
        yes=yes,
    )


def _run(
    ns: argparse.Namespace,
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    stdout: IO[str] = io.StringIO()
    stderr: IO[str] = io.StringIO()
    code = _command(ns, stdout=stdout, stderr=stderr, cwd=cwd)
    return code, stdout.getvalue(), stderr.getvalue()


# ---------------------------------------------------------------------------
# Exit-code constants
# ---------------------------------------------------------------------------


def test_exit_codes_are_stable() -> None:
    assert EXIT_OK == 0
    assert EXIT_USER_ABORT == 1
    assert EXIT_USAGE == 2
    assert EXIT_INTERNAL == 3


# ---------------------------------------------------------------------------
# Help / target listing
# ---------------------------------------------------------------------------


def test_register_attaches_subparser_with_description() -> None:
    parser = argparse.ArgumentParser(prog="ajolopy")
    sub = parser.add_subparsers(dest="cmd")
    register(sub)
    formatted = parser.format_help()
    assert "deploy" in formatted


def test_help_description_lists_every_target() -> None:
    description = _build_help_description()
    for name in ("docker", "fly", "railway", "render", "vercel"):
        assert name in description
    # The description preserves registration order so the docker
    # reference impl is listed first.
    assert description.index("docker") < description.index("fly")


# ---------------------------------------------------------------------------
# Unknown target / missing positional
# ---------------------------------------------------------------------------


def test_unknown_target_exits_usage(tmp_path: Path) -> None:
    code, stdout, stderr = _run(_namespace("nope", out_dir=tmp_path), cwd=tmp_path)
    del stdout
    assert code == EXIT_USAGE
    assert "nope" in stderr
    # The error lists known targets — assert on the docker entry which is
    # the v0.1 reference impl.
    assert "docker" in stderr


# ---------------------------------------------------------------------------
# Out-dir handling
# ---------------------------------------------------------------------------


def test_missing_out_dir_exits_usage(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    code, _stdout, stderr = _run(_namespace("docker", out_dir=missing), cwd=tmp_path)
    assert code == EXIT_USAGE
    assert str(missing) in stderr


# ---------------------------------------------------------------------------
# Docker target — happy paths
# ---------------------------------------------------------------------------


def test_docker_writes_two_files(tmp_path: Path) -> None:
    code, stdout, stderr = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_OK, stderr
    assert (tmp_path / "Dockerfile.prod").is_file()
    assert (tmp_path / ".dockerignore").is_file()
    assert "Dockerfile.prod" in stdout
    assert ".dockerignore" in stdout


def test_docker_prints_next_steps(tmp_path: Path) -> None:
    _, stdout, _ = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    assert "Next steps:" in stdout
    assert "docker build -f Dockerfile.prod" in stdout
    assert "docker run -p 3000:3000" in stdout


def test_docker_dry_run_does_not_write(tmp_path: Path) -> None:
    code, stdout, _ = _run(_namespace("docker", out_dir=tmp_path, dry_run=True), cwd=tmp_path)
    assert code == EXIT_OK
    assert not (tmp_path / "Dockerfile.prod").exists()
    assert not (tmp_path / ".dockerignore").exists()
    assert "# Dockerfile.prod" in stdout
    assert "# .dockerignore" in stdout


def test_docker_dry_run_does_not_print_wrote_header(tmp_path: Path) -> None:
    _, stdout, _ = _run(_namespace("docker", out_dir=tmp_path, dry_run=True), cwd=tmp_path)
    assert "Wrote:" not in stdout


def test_docker_existing_files_without_force_exits_usage(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile.prod").write_text("stale\n", encoding="utf-8")
    code, _stdout, stderr = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_USAGE
    assert "Dockerfile.prod" in stderr
    assert "--force" in stderr
    # The original content must be untouched.
    assert (tmp_path / "Dockerfile.prod").read_text(encoding="utf-8") == "stale\n"


def test_docker_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile.prod").write_text("stale\n", encoding="utf-8")
    code, _stdout, _stderr = _run(
        _namespace("docker", out_dir=tmp_path, force=True),
        cwd=tmp_path,
    )
    assert code == EXIT_OK
    contents = (tmp_path / "Dockerfile.prod").read_text(encoding="utf-8")
    assert "syntax=docker/dockerfile" in contents


def test_docker_out_dir_routes_writes(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    code, _stdout, _stderr = _run(
        _namespace("docker", out_dir=elsewhere),
        cwd=tmp_path,
    )
    assert code == EXIT_OK
    assert (elsewhere / "Dockerfile.prod").is_file()
    assert not (tmp_path / "Dockerfile.prod").exists()


def test_yes_flag_is_accepted_without_error(tmp_path: Path) -> None:
    code, _stdout, _stderr = _run(
        _namespace("docker", out_dir=tmp_path, yes=True),
        cwd=tmp_path,
    )
    assert code == EXIT_OK


# ---------------------------------------------------------------------------
# Fly target — real implementation (AJ-42)
# ---------------------------------------------------------------------------


def test_fly_writes_fly_toml(tmp_path: Path) -> None:
    code, stdout, stderr = _run(_namespace("fly", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_OK, stderr
    assert (tmp_path / "fly.toml").is_file()
    assert list(tmp_path.iterdir()) == [tmp_path / "fly.toml"]
    assert "fly.toml" in stdout


def test_fly_prints_next_steps(tmp_path: Path) -> None:
    _, stdout, _ = _run(_namespace("fly", out_dir=tmp_path), cwd=tmp_path)
    assert "Next steps:" in stdout
    for expected in (
        "fly auth login",
        "fly secrets set ANTHROPIC_API_KEY=",
        "fly secrets set DATABASE_URL=",
        "fly launch",
        "fly deploy",
    ):
        assert expected in stdout


# ---------------------------------------------------------------------------
# Railway target — real manifest writer (AJ-43)
# ---------------------------------------------------------------------------


def test_railway_writes_manifest(tmp_path: Path) -> None:
    code, stdout, stderr = _run(_namespace("railway", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_OK, stderr
    assert (tmp_path / "railway.json").is_file()
    assert "railway.json" in stdout


def test_railway_prints_next_steps(tmp_path: Path) -> None:
    _, stdout, _ = _run(_namespace("railway", out_dir=tmp_path), cwd=tmp_path)
    assert "Next steps:" in stdout
    assert "railway login" in stdout
    assert "railway link" in stdout
    assert "railway up" in stdout


# ---------------------------------------------------------------------------
# Render target — real manifest writer (AJ-44)
# ---------------------------------------------------------------------------


def test_render_writes_render_yaml(tmp_path: Path) -> None:
    code, stdout, stderr = _run(_namespace("render", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_OK, stderr
    # Exactly one file on disk: render.yaml.
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["render.yaml"]
    assert (tmp_path / "render.yaml").is_file()
    # Both next-step strings reach stdout.
    assert "Commit and push the generated render.yaml to your repo." in stdout
    assert "Visit https://dashboard.render.com/blueprints to apply the blueprint." in stdout


# ---------------------------------------------------------------------------
# Vercel target — warning-gate CLI integration (AJ-45)
# ---------------------------------------------------------------------------


def test_vercel_with_yes_writes_vercel_json(tmp_path: Path) -> None:
    code, stdout, stderr = _run(
        _namespace("vercel", out_dir=tmp_path, yes=True),
        cwd=tmp_path,
    )
    assert code == EXIT_OK, stderr
    manifest = tmp_path / "vercel.json"
    assert manifest.is_file()
    assert "vercel.json" in stdout
    # Sanity check on the payload — the unit tests assert the full shape.
    assert '"@vercel/python"' in manifest.read_text(encoding="utf-8")


def test_vercel_with_yes_prints_next_steps(tmp_path: Path) -> None:
    _, stdout, _ = _run(
        _namespace("vercel", out_dir=tmp_path, yes=True),
        cwd=tmp_path,
    )
    assert "vercel login" in stdout
    assert "vercel link" in stdout
    assert "vercel deploy --prod" in stdout


def test_vercel_user_declines_exits_user_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user declines the warning gate, the CLI exits 1 and writes nothing."""
    _install_vercel_target_with_stdin(monkeypatch, "n\n")
    code, _stdout, stderr = _run(_namespace("vercel", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_USER_ABORT
    assert "vercel" in stderr.lower()
    assert not (tmp_path / "vercel.json").exists()


def test_vercel_user_accepts_via_injected_stdin_writes_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting the gate via injected stdin yields the same result as ``--yes``."""
    _install_vercel_target_with_stdin(monkeypatch, "y\n")
    code, stdout, stderr = _run(_namespace("vercel", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_OK, stderr
    assert (tmp_path / "vercel.json").is_file()
    assert "vercel.json" in stdout


def _install_vercel_target_with_stdin(
    monkeypatch: pytest.MonkeyPatch,
    stdin_text: str,
) -> None:
    """Swap the registered ``vercel`` target for one with an injected stdin.

    The new registry is a snapshot of the live one, so every other
    target (``docker`` / ``fly`` / ``railway`` / ``render``) keeps its
    real registration — only the slot under test gets swapped.
    """
    from ajolopy.cli.deploy.registry import _REGISTRY
    from ajolopy.cli.deploy.vercel import VercelTarget

    target = VercelTarget(stdin=io.StringIO(stdin_text), stdout=io.StringIO())
    monkeypatch.setattr(
        "ajolopy.cli.deploy.registry._REGISTRY",
        {**_REGISTRY, "vercel": target},
    )


# ---------------------------------------------------------------------------
# Project-name + app-module discovery
# ---------------------------------------------------------------------------


def test_project_name_falls_back_to_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "acme-app"
    project_dir.mkdir()
    _, stdout, _ = _run(_namespace("docker", out_dir=project_dir), cwd=tmp_path)
    assert "acme-app:latest" in stdout


def test_project_name_reads_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "neon-svc"\nversion = "0.0.1"\n',
        encoding="utf-8",
    )
    _, stdout, _ = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    assert "neon-svc:latest" in stdout


def test_malformed_pyproject_returns_internal(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname=", encoding="utf-8")
    code, _stdout, stderr = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    assert code == EXIT_INTERNAL
    assert "pyproject.toml" in stderr


def test_app_module_falls_back_to_default_when_no_src(tmp_path: Path) -> None:
    _, _stdout, _ = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    # The Dockerfile uses ``main:app`` in the CMD when no src/<pkg>/main.py exists.
    contents = (tmp_path / "Dockerfile.prod").read_text(encoding="utf-8")
    assert "main:app" in contents


def test_app_module_uses_single_src_package(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "neon_svc"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text("app = object()\n", encoding="utf-8")
    _, _stdout, _ = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    contents = (tmp_path / "Dockerfile.prod").read_text(encoding="utf-8")
    assert "neon_svc.main:app" in contents


def test_app_module_falls_back_with_multiple_packages(tmp_path: Path) -> None:
    for name in ("alpha", "beta"):
        pkg = tmp_path / "src" / name
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "main.py").write_text("app = object()\n", encoding="utf-8")
    _, _stdout, _ = _run(_namespace("docker", out_dir=tmp_path), cwd=tmp_path)
    contents = (tmp_path / "Dockerfile.prod").read_text(encoding="utf-8")
    # Falls back to the safe default because the discovery is ambiguous.
    assert "main:app" in contents
    assert "alpha.main:app" not in contents
    assert "beta.main:app" not in contents
