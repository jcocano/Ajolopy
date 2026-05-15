"""``--app module:var`` override resolution."""

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
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = dev_cmd._command(args, stdout=stdout, stderr=stderr, cwd=cwd)
    return code, stdout.getvalue(), stderr.getvalue()


def _install_module(tmp_path: Path, name: str, body: str) -> None:
    """Drop ``<name>.py`` under ``tmp_path`` and prepend it to sys.path."""
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))


@pytest.fixture(autouse=True)
def _scrub_sys_path() -> Any:  # pyright: ignore[reportUnusedFunction]
    original = list(sys.path)
    snapshot = set(sys.modules.keys())
    yield
    sys.path[:] = original
    for name in set(sys.modules.keys()) - snapshot:
        sys.modules.pop(name, None)


class TestAppOverrideHappyPath:
    def test_resolves_module_and_var(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        _install_module(tmp_path, "explicit_target", "app = object()\n")

        code, _out, err = _run(
            ["dev", "--app", "explicit_target:app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.app == "explicit_target:app"

    def test_accepts_alternative_var_name(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        _install_module(tmp_path, "alt_target", "my_asgi_app = object()\n")

        code, _out, err = _run(
            ["dev", "--app", "alt_target:my_asgi_app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.app == "alt_target:my_asgi_app"

    def test_strips_whitespace_around_components(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        _install_module(tmp_path, "padded_target", "app = object()\n")

        code, _out, err = _run(
            ["dev", "--app", " padded_target : app ", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.app == "padded_target:app"


class TestAppOverrideFailures:
    def test_unknown_module_exits_1(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, _out, err = _run(
            ["dev", "--app", "no.such.module:app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "could not import module 'no.such.module'" in err
        assert stub_uvicorn.instances == []

    def test_missing_var_exits_1(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        _install_module(tmp_path, "real_module", "app = object()\n")

        code, _out, err = _run(
            ["dev", "--app", "real_module:no_such_var", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_DISCOVERY
        assert "attribute 'no_such_var'" in err
        assert stub_uvicorn.instances == []

    def test_malformed_target_exits_2(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, _out, err = _run(
            ["dev", "--app", "missing-colon-here", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_USAGE
        assert "module:var" in err
        assert stub_uvicorn.instances == []

    def test_empty_module_or_var_exits_2(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, _out, err = _run(
            ["dev", "--app", ":app", "--no-reload"],
            cwd=tmp_path,
        )
        assert code == dev_cmd.EXIT_USAGE
        assert "missing" in err
