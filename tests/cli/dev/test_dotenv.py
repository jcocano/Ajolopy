"""``ajolopy dev`` auto-loads ``cwd/.env`` before importing the user module.

Regression suite for AJ-88: the wizard's "Next steps" tells the user to
``cp .env.example .env`` and then ``ajolopy dev``, so the dev command
MUST source ``.env`` itself before the user module is imported.
Otherwise providers that read ``ANTHROPIC_API_KEY`` /
``OPENAI_API_KEY`` / ``GOOGLE_API_KEY`` directly via :func:`os.environ`
crash at boot.

The tests exercise :func:`_load_dotenv` directly (it accepts an injected
``environ`` mapping so production ``os.environ`` is never touched) and
the full ``_command`` pipeline through ``_run`` to assert the load
happens BEFORE the autodetect import step.
"""

import io
import os
import sys
import textwrap
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


class TestLoadDotenvHelper:
    """Direct exercises of :func:`dev._load_dotenv` against an injected env."""

    def test_loads_keys_from_dotenv(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
        env: dict[str, str] = {}

        loaded = dev_cmd._load_dotenv(cwd=tmp_path, environ=env)

        assert loaded is True
        assert env["FOO"] == "bar"
        assert env["BAZ"] == "qux"

    def test_returns_false_when_no_dotenv(self, tmp_path: Path) -> None:
        env: dict[str, str] = {}

        loaded = dev_cmd._load_dotenv(cwd=tmp_path, environ=env)

        assert loaded is False
        assert env == {}

    def test_shell_env_takes_precedence_over_dotenv(self, tmp_path: Path) -> None:
        """Shell wins: pre-existing keys MUST NOT be overwritten by ``.env``."""
        (tmp_path / ".env").write_text("FOO=from-dotenv\nNEW=hello\n", encoding="utf-8")
        env: dict[str, str] = {"FOO": "from-shell"}

        loaded = dev_cmd._load_dotenv(cwd=tmp_path, environ=env)

        assert loaded is True
        # Shell-exported value preserved.
        assert env["FOO"] == "from-shell"
        # .env-only value applied.
        assert env["NEW"] == "hello"

    def test_handles_comments_blank_lines_and_quotes(self, tmp_path: Path) -> None:
        """python-dotenv handles the usual ``.env`` features cleanly."""
        (tmp_path / ".env").write_text(
            textwrap.dedent(
                """\
                # comment line — ignored
                FOO=bar

                BAZ="quoted value"
                # trailing comment
                ANTHROPIC_API_KEY=sk-ant-fake
                """
            ),
            encoding="utf-8",
        )
        env: dict[str, str] = {}

        loaded = dev_cmd._load_dotenv(cwd=tmp_path, environ=env)

        assert loaded is True
        assert env["FOO"] == "bar"
        assert env["BAZ"] == "quoted value"
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-fake"

    def test_skips_bare_keys_without_value(self, tmp_path: Path) -> None:
        """``KEY=`` should NOT clobber a shell-exported value with empty string."""
        (tmp_path / ".env").write_text("EMPTY_KEY\nFOO=bar\n", encoding="utf-8")
        env: dict[str, str] = {"EMPTY_KEY": "preserved"}

        loaded = dev_cmd._load_dotenv(cwd=tmp_path, environ=env)

        assert loaded is True
        assert env["EMPTY_KEY"] == "preserved"
        assert env["FOO"] == "bar"

    def test_does_not_walk_to_parent_directory(self, tmp_path: Path) -> None:
        """Only ``cwd/.env`` is read; parent ``.env`` files are NOT picked up."""
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        (parent / ".env").write_text("PARENT_KEY=should-not-leak\n", encoding="utf-8")
        env: dict[str, str] = {}

        loaded = dev_cmd._load_dotenv(cwd=child, environ=env)

        assert loaded is False
        assert "PARENT_KEY" not in env


class TestLoadDotenvIntegratedWithCommand:
    """Wire :func:`_load_dotenv` through the real ``_command`` entry point.

    The autodetect path runs ``importlib.import_module`` of
    ``<package>.main``. We use a ``main.py`` that reads an env var at
    import time to PROVE the load happens BEFORE the user module
    executes.
    """

    def test_dotenv_visible_during_user_module_import(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pick a token that is extremely unlikely to be in the test shell.
        secret_value = "sk-ant-fake-aj88-regression"  # noqa: S105 — fake test token
        marker_key = "AJ88_DEV_DOTENV_MARKER"
        monkeypatch.delenv(marker_key, raising=False)

        (tmp_path / ".env").write_text(
            f"{marker_key}={secret_value}\n",
            encoding="utf-8",
        )
        # ``main.py`` reads the env var at import time and crashes if it
        # is missing — mirroring how the Anthropic / OpenAI clients
        # behave when their API keys are absent.
        project_factory(
            tmp_path,
            package="aj88app",
            main_body=textwrap.dedent(
                f"""\
                import os

                _value = os.environ["{marker_key}"]
                app = object()
                """
            ),
        )

        try:
            code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)
        finally:
            # The integrated path uses the real ``os.environ``; clean up
            # so the marker does not leak into sibling tests.
            os.environ.pop(marker_key, None)
            sys.modules.pop("aj88app", None)
            sys.modules.pop("aj88app.main", None)

        assert code == dev_cmd.EXIT_OK, err
        # The stub captures the resolved entry point so we know
        # ``import_module`` ran without raising ``KeyError``.
        assert stub_uvicorn.instances[0].config.app == "aj88app.main:app"

    def test_command_succeeds_without_dotenv_present(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        """The autoload step must be opt-in by file presence, never required."""
        project_factory(tmp_path, package="aj88noenv")

        try:
            code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)
        finally:
            sys.modules.pop("aj88noenv", None)
            sys.modules.pop("aj88noenv.main", None)

        assert code == dev_cmd.EXIT_OK, err
