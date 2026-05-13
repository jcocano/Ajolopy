"""Tests for ``render_dockerignore``.

Covers the literal entry list (every doc 07 line, in order) and the
no-trailing-blank-line invariant that lets callers concatenate their
own entries safely.
"""

from pathlib import Path

from ajolopy.templates.docker import render_dockerignore

_EXPECTED_LINES = (
    "__pycache__/",
    "*.py[cod]",
    "*$py.class",
    "*.so",
    ".Python",
    ".venv/",
    "venv/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".env",
    ".env.local",
    ".env.*.local",
    ".vscode/",
    ".idea/",
    "*.swp",
    "tests/",
    "docs/",
    ".github/",
    ".git/",
    "README.md",
)


class TestDockerignoreContent:
    def test_contains_every_doc_07_entry_in_order(self) -> None:
        output = render_dockerignore()
        # ``render_dockerignore`` ends with a trailing newline; the
        # split below drops the empty trailing element so the strict
        # equality compares the doc lines 1-for-1.
        body_lines = output.split("\n")
        assert body_lines[-1] == ""
        assert tuple(body_lines[:-1]) == _EXPECTED_LINES

    def test_each_entry_appears_exactly_once(self) -> None:
        # Match against full lines (not substrings) so entries like
        # ``venv/`` and ``.venv/`` do not collide.
        lines = render_dockerignore().splitlines()
        for entry in _EXPECTED_LINES:
            assert lines.count(entry) == 1, f"{entry!r} appeared more than once"


class TestDockerignoreLayout:
    def test_no_leading_blank_line(self) -> None:
        output = render_dockerignore()
        assert not output.startswith("\n")

    def test_no_trailing_blank_lines(self) -> None:
        output = render_dockerignore()
        # One terminating newline is fine (POSIX convention). Two would
        # leave a blank line at the bottom, which is what callers care
        # about when concatenating their own extension.
        assert output.endswith("\n")
        assert not output.endswith("\n\n")

    def test_deterministic(self) -> None:
        assert render_dockerignore() == render_dockerignore()


class TestDockerignoreSnapshot:
    def test_matches_committed_snapshot(self) -> None:
        snapshot = Path(__file__).parent / "__snapshots__" / "dockerignore.txt"
        assert render_dockerignore() == snapshot.read_text()
