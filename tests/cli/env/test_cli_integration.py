"""CLI integration: registration, colon-alias rewrite, ``--help`` plumbing."""

import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, cast

import pytest

from ajolopy.cli.commands import env as env_cmd
from ajolopy.cli.dispatcher import COLON_ALIASES, _rewrite_colon_aliases, build_parser, main

from .conftest import SAMPLE_CONFIG


class TestSubcommandsRegistered:
    def test_env_show_resolves_to_handler(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["env-show"])
        assert args.func is env_cmd.cmd_env_show

    def test_env_validate_resolves_to_handler(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["env-validate"])
        assert args.func is env_cmd.cmd_env_validate

    def test_env_diff_resolves_to_handler(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["env-diff"])
        assert args.func is env_cmd.cmd_env_diff


class TestColonAliasMap:
    def test_alias_map_exposes_three_entries(self) -> None:
        # Tests pin the surface so an accidental rename of any of the
        # three sub-aliases regresses noisily.
        assert COLON_ALIASES == {
            "env:show": "env-show",
            "env:validate": "env-validate",
            "env:diff": "env-diff",
        }

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["env:show"], ["env-show"]),
            (["env:show", "--ci"], ["env-show", "--ci"]),
            (["env:validate"], ["env-validate"]),
            (["env:diff", "--ci"], ["env-diff", "--ci"]),
        ],
    )
    def test_rewrites_first_argv_element(
        self,
        argv: list[str],
        expected: list[str],
    ) -> None:
        assert _rewrite_colon_aliases(argv) == expected

    def test_non_colon_subcommand_passes_through(self) -> None:
        assert _rewrite_colon_aliases(["dev", "--no-reload"]) == ["dev", "--no-reload"]

    def test_empty_argv_handled_gracefully(self) -> None:
        assert _rewrite_colon_aliases([]) == []

    def test_only_first_element_is_considered(self) -> None:
        # A user-supplied value that happens to look like ``env:show``
        # later in argv must not be rewritten.
        argv = ["dev", "--watch", "env:show"]
        assert _rewrite_colon_aliases(argv) == argv

    def test_main_drives_colon_form_through_dispatcher(
        self,
        tmp_path: Path,
        project_factory: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Wire up a minimal project so env:show has work to do.
        project_factory(tmp_path, package="envapp", config_body=SAMPLE_CONFIG)
        monkeypatch.chdir(tmp_path)
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "APP_ENV", "LOG_LEVEL"):
            monkeypatch.delenv(name, raising=False)

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["env:show"])
        assert code == env_cmd.EXIT_OK
        # The handler ran — every declared field is in the output.
        out = buf.getvalue()
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "APP_ENV", "LOG_LEVEL"):
            assert name in out


class TestHelpStringSurfacesColonForm:
    @pytest.mark.parametrize(
        ("internal", "colon"),
        [
            ("env-show", "env:show"),
            ("env-validate", "env:validate"),
            ("env-diff", "env:diff"),
        ],
    )
    def test_help_text_mentions_documented_colon_form(
        self,
        internal: str,
        colon: str,
    ) -> None:
        parser = build_parser()
        # argparse's subparser registry is private; we drill through
        # _actions to fetch the per-subcommand parser without inventing
        # a new public seam.
        subparsers_action = next(action for action in parser._actions if action.dest == "cmd")
        choices = cast("dict[str, Any]", subparsers_action.choices)
        target = choices[internal]
        description: str = target.description
        assert colon in description
