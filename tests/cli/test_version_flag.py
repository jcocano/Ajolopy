"""Top-level ``ajolopy --version`` flag (regression for AJ-83).

The dispatcher used to require a subcommand even when the user only
asked for the version, so ``ajolopy --version`` would error with
``the following arguments are required: subcommand`` and exit ``2``.
The fix adds a top-level argparse ``--version`` action that prints the
package version and exits ``0`` without parsing a subcommand.
"""

import pytest

from ajolopy import __version__
from ajolopy.cli import main as cli_main


class TestTopLevelVersionFlag:
    def test_top_level_version_flag_prints_version(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``ajolopy --version`` writes ``ajolopy <version>`` and exits 0."""
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        # argparse's ``version`` action writes to stdout in modern Python.
        assert f"ajolopy {__version__}" in captured.out

    def test_top_level_version_flag_does_not_require_subcommand(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The ``subcommand required`` usage error must not appear (AJ-83)."""
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "the following arguments are required" not in combined
