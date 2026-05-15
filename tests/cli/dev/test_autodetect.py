"""Auto-detection branches for ``ajolopy dev``.

Each test isolates one decision point of the AJ-32 convention
discovery so a regression points at the broken branch immediately.
"""

import io
import sys
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import dev as dev_cmd
from ajolopy.cli.dispatcher import build_parser


def _run(
    argv: list[str],
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    """Drive ``_command`` with StringIO buffers; return (code, out, err)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = dev_cmd._command(args, stdout=stdout, stderr=stderr, cwd=cwd)
    return code, stdout.getvalue(), stderr.getvalue()


class TestAutodetectHappyPath:
    def test_resolves_single_package_with_app(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        project_factory(tmp_path, package="myapp")

        code, out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_OK, err
        instances = stub_uvicorn.instances
        assert len(instances) == 1
        assert instances[0].config.app == "myapp.main:app"
        assert instances[0].run_called is True
        assert "myapp.main:app" in out


class TestAutodetectFailures:
    def test_missing_src_dir_exits_1(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        # tmp_path has no src/ subdir.
        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "no 'src/'" in err
        assert "--app" in err

    def test_two_packages_under_src_exits_1(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        project_factory(
            tmp_path,
            package="myapp",
            extra_packages=("altpkg",),
        )

        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "multiple packages" in err
        assert "myapp" in err
        assert "altpkg" in err

    def test_no_package_under_src_exits_1(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        (tmp_path / "src").mkdir()
        # Drop a stray file + a __pycache__ dir; neither should count.
        (tmp_path / "src" / "notes.txt").write_text("hello\n", encoding="utf-8")
        (tmp_path / "src" / "__pycache__").mkdir()

        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "no Python package" in err

    def test_missing_main_py_exits_1(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        project_factory(tmp_path, package="myapp", create_main=False)

        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "main.py" in err

    def test_main_py_missing_app_attr_exits_1(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        project_factory(
            tmp_path,
            package="noappapp",
            main_body="other = object()\n",
        )

        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "does not define an 'app' attribute" in err


class TestAutodetectSyspathHandling:
    def test_inserts_src_on_sys_path_when_absent(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_factory(tmp_path, package="myapp")

        # Snapshot sys.path so the cleanup leaves the process intact.
        original = list(sys.path)
        try:
            monkeypatch.setattr(sys, "path", original.copy())
            assert str((tmp_path / "src").resolve()) not in sys.path
            code, _out, _err = _run(["dev", "--no-reload"], cwd=tmp_path)
        finally:
            sys.path[:] = original
            sys.modules.pop("myapp", None)
            sys.modules.pop("myapp.main", None)

        assert code == dev_cmd.EXIT_OK
        assert stub_uvicorn.instances[0].config.app == "myapp.main:app"
