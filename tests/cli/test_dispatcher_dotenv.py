"""Dispatcher auto-loads ``cwd/.env`` before any subcommand (AJ-93).

AJ-88 added ``.env`` autoload to ``ajolopy dev`` only. ``ajolopy eval``,
``ajolopy doctor``, and any other subcommand that imports user code
still crashed at boot with ``ANTHROPIC_API_KEY missing`` when run from a
project root whose ``.env`` declared the key. AJ-93 hoisted the load
into the dispatcher so every subcommand inherits the behaviour.

These tests pin the contract: the load happens BEFORE the subcommand
handler runs, only ``cwd/.env`` is read (no parent walk), and shell-set
variables still win over ``.env`` entries.
"""

from pathlib import Path

import pytest

from ajolopy.cli import dispatcher


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test from a tmp dir so ``Path.cwd()`` returns it.

    ``monkeypatch.chdir`` auto-rolls back at fixture teardown, so a plain
    ``return`` is correct (no yield/cleanup needed).
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _install_recording_handler(
    monkeypatch: pytest.MonkeyPatch,
    record: dict[str, object],
) -> None:
    """Replace ``main``'s subcommand dispatch with a recorder.

    The recorder captures ``os.environ`` at the moment the subcommand
    would run, so the test can assert the dispatcher loaded ``.env``
    BEFORE handing off.
    """
    import os as _os

    real_parser = dispatcher.build_parser()

    def fake_build_parser() -> object:
        return real_parser

    def fake_func(_args: object) -> int:
        record["env_at_handler_time"] = dict(_os.environ)
        return 0

    real_parse_args = real_parser.parse_args

    def hijacked_parse_args(*a: object, **kw: object) -> object:
        ns = real_parse_args(*a, **kw)
        ns.func = fake_func
        return ns

    monkeypatch.setattr(real_parser, "parse_args", hijacked_parse_args)
    monkeypatch.setattr(dispatcher, "build_parser", fake_build_parser)


class TestDispatcherDotenvAutoload:
    def test_env_from_dotenv_visible_in_handler(
        self,
        isolated_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keys declared in ``cwd/.env`` reach the subcommand handler."""
        (isolated_cwd / ".env").write_text(
            "AJ93_TEST_KEY=from-dotenv\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("AJ93_TEST_KEY", raising=False)

        record: dict[str, object] = {}
        _install_recording_handler(monkeypatch, record)

        dispatcher.main(["doctor"])

        env_at_handler = record["env_at_handler_time"]
        assert isinstance(env_at_handler, dict)
        assert env_at_handler.get("AJ93_TEST_KEY") == "from-dotenv", (
            "Dispatcher did not load cwd/.env before invoking the subcommand."
        )

    def test_shell_env_wins_over_dotenv(
        self,
        isolated_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A shell-set value is preserved; the ``.env`` value is ignored."""
        (isolated_cwd / ".env").write_text(
            "AJ93_TEST_KEY=from-dotenv\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("AJ93_TEST_KEY", "from-shell")

        record: dict[str, object] = {}
        _install_recording_handler(monkeypatch, record)

        dispatcher.main(["doctor"])

        env_at_handler = record["env_at_handler_time"]
        assert isinstance(env_at_handler, dict)
        assert env_at_handler.get("AJ93_TEST_KEY") == "from-shell"

    def test_no_dotenv_file_runs_cleanly(
        self,
        isolated_cwd: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Absence of ``.env`` is not an error — dispatch proceeds normally."""
        # Sanity: no .env exists at the tmp cwd.
        assert not (isolated_cwd / ".env").exists()

        record: dict[str, object] = {}
        _install_recording_handler(monkeypatch, record)

        rc = dispatcher.main(["doctor"])
        assert rc == 0
        assert "env_at_handler_time" in record
