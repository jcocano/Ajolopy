"""Flag plumbing: ``--host``, ``--port``, ``--watch``, ``--no-reload``."""

import io
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


@pytest.fixture
def project(tmp_path: Path, project_factory: Any) -> Path:
    project_factory(tmp_path, package="myapp")
    return tmp_path


class TestHostPort:
    def test_host_forwarded_to_uvicorn_config(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, out, _err = _run(
            ["dev", "--host", "0.0.0.0", "--no-reload"],  # noqa: S104 -- test asserts the value is forwarded
            cwd=project,
        )
        assert code == dev_cmd.EXIT_OK
        assert stub_uvicorn.instances[0].config.host == "0.0.0.0"  # noqa: S104
        assert "http://0.0.0.0:8000" in out

    def test_port_forwarded_to_uvicorn_config(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, out, _err = _run(
            ["dev", "--port", "8080", "--no-reload"],
            cwd=project,
        )
        assert code == dev_cmd.EXIT_OK
        assert stub_uvicorn.instances[0].config.port == 8080
        assert "http://127.0.0.1:8080" in out

    def test_defaults_when_omitted(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, _out, _err = _run(["dev", "--no-reload"], cwd=project)
        assert code == dev_cmd.EXIT_OK
        config = stub_uvicorn.instances[0].config
        assert config.host == "127.0.0.1"
        assert config.port == 8000


class TestReloadToggle:
    def test_no_reload_disables_reload_on_config(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, out, _err = _run(["dev", "--no-reload"], cwd=project)
        assert code == dev_cmd.EXIT_OK
        assert stub_uvicorn.instances[0].config.reload is False
        assert "Reload:   off" in out

    def test_reload_enabled_by_default(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, out, _err = _run(["dev"], cwd=project)
        assert code == dev_cmd.EXIT_OK
        config = stub_uvicorn.instances[0].config
        assert config.reload is True
        # uvicorn normalises reload_dirs to Path objects; the project's
        # src/ is the first entry under auto-detect.
        reload_dirs = [str(p) for p in config.reload_dirs]
        assert any(p.endswith("src") for p in reload_dirs)
        assert "Reload:   on" in out


class TestWatchPaths:
    def test_watch_adds_to_reload_dirs(
        self,
        project: Path,
        stub_uvicorn: Any,
        tmp_path: Path,
    ) -> None:
        extra = tmp_path / "extras"
        extra.mkdir()
        code, _out, _err = _run(
            ["dev", "--watch", str(extra)],
            cwd=project,
        )
        assert code == dev_cmd.EXIT_OK
        reload_dirs = [str(p) for p in stub_uvicorn.instances[0].config.reload_dirs]
        assert str(extra.resolve()) in reload_dirs

    def test_watch_repeatable_accepts_multiple_dirs(
        self,
        project: Path,
        stub_uvicorn: Any,
        tmp_path: Path,
    ) -> None:
        # ``--watch`` is ``action="append"``; both entries must reach
        # the resolved ``reload_dirs``. uvicorn's :class:`Config`
        # normalises the list (resolving patterns + de-duping nested
        # children), so we only assert presence — not order.
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        code, _out, _err = _run(
            ["dev", "--watch", str(first), "--watch", str(second)],
            cwd=project,
        )
        assert code == dev_cmd.EXIT_OK
        reload_dirs = [str(p) for p in stub_uvicorn.instances[0].config.reload_dirs]
        assert str(first.resolve()) in reload_dirs
        assert str(second.resolve()) in reload_dirs

    def test_no_reload_drops_reload_dirs(
        self,
        project: Path,
        stub_uvicorn: Any,
        tmp_path: Path,
    ) -> None:
        extra = tmp_path / "extras"
        extra.mkdir()
        code, _out, _err = _run(
            ["dev", "--no-reload", "--watch", str(extra)],
            cwd=project,
        )
        assert code == dev_cmd.EXIT_OK
        # When reload is disabled uvicorn ignores reload_dirs anyway —
        # the CLI elects to not pass it to keep the Config minimal.
        config = stub_uvicorn.instances[0].config
        assert config.reload is False


class TestDotEnvWatching:
    def test_dotenv_in_cwd_enables_filtered_includes(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        project_factory(tmp_path, package="myapp", create_env=True)
        code, _out, _err = _run(["dev"], cwd=tmp_path)
        assert code == dev_cmd.EXIT_OK
        config = stub_uvicorn.instances[0].config
        assert config.reload is True
        reload_dirs = [str(p) for p in config.reload_dirs]
        assert str(tmp_path.resolve()) in reload_dirs
        includes = list(config.reload_includes)
        assert "**/.env" in includes
        assert "*.py" in includes

    def test_no_dotenv_skips_filter(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        project_factory(tmp_path, package="myapp", create_env=False)
        code, _out, _err = _run(["dev"], cwd=tmp_path)
        assert code == dev_cmd.EXIT_OK
        config = stub_uvicorn.instances[0].config
        # uvicorn defaults reload_includes to ``['*.py']`` when nothing
        # is passed; the CLI only sets the filter when ``.env`` exists.
        includes = list(config.reload_includes)
        assert "**/.env" not in includes


class TestBanner:
    def test_banner_lists_app_url_watch_reload(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, out, _err = _run(
            ["dev", "--host", "0.0.0.0", "--port", "9000", "--no-reload"],  # noqa: S104 -- test asserts the value is forwarded
            cwd=project,
        )
        assert code == dev_cmd.EXIT_OK
        assert "App:" in out
        assert "myapp.main:app" in out
        assert "URL:" in out
        assert "http://0.0.0.0:9000" in out
        assert "Watching:" in out
        assert "Reload:   off" in out

    def test_banner_skips_emoji_on_non_tty(
        self,
        project: Path,
        stub_uvicorn: Any,
    ) -> None:
        code, out, _err = _run(["dev", "--no-reload"], cwd=project)
        assert code == dev_cmd.EXIT_OK
        # StringIO is not a TTY → no emoji.
        assert "\U0001f4e1" not in out
        assert "Starting Ajolopy dev server..." in out
