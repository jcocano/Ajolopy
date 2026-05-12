"""Tests for the ``protect-main`` pre-push guard."""

import io
from typing import TYPE_CHECKING

from tools import protect_main

if TYPE_CHECKING:
    import pytest


def _stdin(*lines: str) -> io.StringIO:
    """Build a stdin-like object holding pre-push ref lines."""
    return io.StringIO("\n".join(lines) + ("\n" if lines else ""))


class TestProtectMain:
    def test_allows_push_to_feature_branch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        stdin = _stdin(
            "refs/heads/feature/foo abc123 refs/heads/feature/foo def456",
        )
        assert protect_main.check(stdin) == 0

    def test_rejects_push_to_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        stdin = _stdin("refs/heads/main abc123 refs/heads/main def456")
        assert protect_main.check(stdin) == 1
        err = capsys.readouterr().err
        assert "direct pushes to `main` are not allowed" in err
        assert protect_main.BYPASS_ENV in err

    def test_rejects_when_any_ref_targets_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Multi-ref push: one feature ref + one to main → reject.
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        stdin = _stdin(
            "refs/heads/feature/foo abc123 refs/heads/feature/foo def456",
            "refs/heads/feature/bar 111111 refs/heads/main 222222",
        )
        assert protect_main.check(stdin) == 1

    def test_bypass_env_allows_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(protect_main.BYPASS_ENV, "1")
        stdin = _stdin("refs/heads/main abc123 refs/heads/main def456")
        assert protect_main.check(stdin) == 0

    def test_bypass_env_other_values_do_not_bypass(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Only the literal value "1" bypasses; "true"/"yes" must NOT.
        monkeypatch.setenv(protect_main.BYPASS_ENV, "true")
        stdin = _stdin("refs/heads/main abc123 refs/heads/main def456")
        assert protect_main.check(stdin) == 1

    def test_empty_stdin_allowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ``git push`` with nothing to push (e.g., already up-to-date).
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        assert protect_main.check(io.StringIO("")) == 0

    def test_malformed_line_skipped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        stdin = _stdin("garbage", "refs/heads/feat abc refs/heads/feat def")
        assert protect_main.check(stdin) == 0

    def test_pre_commit_env_var_rejects_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # pre-commit framework path: stdin may be empty by the time the hook
        # runs, but PRE_COMMIT_REMOTE_BRANCH is exported.
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        monkeypatch.setenv(protect_main.PRE_COMMIT_REMOTE_BRANCH, "refs/heads/main")
        assert protect_main.check(_stdin()) == 1

    def test_pre_commit_env_var_allows_feature(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(protect_main.BYPASS_ENV, raising=False)
        monkeypatch.setenv(
            protect_main.PRE_COMMIT_REMOTE_BRANCH,
            "refs/heads/feature/foo",
        )
        assert protect_main.check(_stdin()) == 0

    def test_bypass_env_wins_over_pre_commit_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(protect_main.BYPASS_ENV, "1")
        monkeypatch.setenv(protect_main.PRE_COMMIT_REMOTE_BRANCH, "refs/heads/main")
        assert protect_main.check(_stdin()) == 0
