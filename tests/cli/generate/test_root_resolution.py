"""Project-root resolution: auto-detect, ``--path`` override, edge cases."""

from pathlib import Path

from ajolopy.cli.commands import generate as generate_cmd
from tests.cli.generate.conftest import invoke_generate, make_project


def test_no_src_directory_without_path_returns_exit_no_project(tmp_cwd: Path) -> None:
    _ = tmp_cwd  # the fixture chdirs into an empty tmp_path.
    result = invoke_generate(["agent", "support"])
    assert result.exit_code == generate_cmd.EXIT_NO_PROJECT
    assert "no 'src/' directory" in result.stderr


def test_empty_src_returns_exit_no_project(tmp_cwd: Path) -> None:
    (tmp_cwd / "src").mkdir()
    result = invoke_generate(["agent", "support"])
    assert result.exit_code == generate_cmd.EXIT_NO_PROJECT
    assert "no Python package" in result.stderr


def test_two_packages_under_src_returns_exit_no_project_with_hint(tmp_cwd: Path) -> None:
    make_project(tmp_cwd, package="alpha")
    make_project(tmp_cwd, package="beta")
    result = invoke_generate(["agent", "support"])
    assert result.exit_code == generate_cmd.EXIT_NO_PROJECT
    assert "multiple packages" in result.stderr
    assert "--path" in result.stderr


def test_explicit_path_override_writes_to_arbitrary_directory(
    tmp_cwd: Path,
    tmp_path: Path,
) -> None:
    _ = tmp_cwd
    target_root = tmp_path / "scratch"
    target_root.mkdir()

    result = invoke_generate(["agent", "support", "--path", str(target_root)])
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr
    written = target_root / "src" / "scratch" / "agents" / "support.py"
    assert written.is_file()


def test_explicit_path_into_existing_project_uses_detected_package(
    tmp_cwd: Path,
    tmp_path: Path,
) -> None:
    """``--path`` keeps templates accurate when it points at a real project."""
    _ = tmp_cwd
    project_root = tmp_path / "real_project"
    make_project(project_root, package="customapp")

    result = invoke_generate(
        ["eval", "support", "--path", str(project_root)],
    )
    assert result.exit_code == generate_cmd.EXIT_OK, result.stderr
    py_target = project_root / "evals" / "support_eval.py"
    assert py_target.is_file()
    assert "from customapp.agents.support import Support" in py_target.read_text(
        encoding="utf-8",
    )
