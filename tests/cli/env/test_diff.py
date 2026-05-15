"""``ajolopy env:diff`` — compare variable NAMES between .env and .env.example."""

import io
import json
from pathlib import Path

from ajolopy.cli.commands import env as env_cmd
from ajolopy.cli.dispatcher import build_parser


def _run(
    argv: list[str],
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    """Drive ``_command_diff`` against StringIO buffers."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = env_cmd._command_diff(
        args,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def _write(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")


class TestReadsBothFiles:
    def test_lists_adds_and_removes(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env", "INTERNAL_DEBUG_TOKEN=x\nAPP_ENV=production\n")
        _write(
            tmp_path / ".env.example",
            "OPENAI_API_KEY=\nREDIS_URL=\nAPP_ENV=\n",
        )
        code, out, _err = _run(["env-diff"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        # .env-only adds.
        assert "In .env but NOT .env.example" in out
        assert "+ INTERNAL_DEBUG_TOKEN" in out
        # .env.example-only removes.
        assert "In .env.example but NOT .env" in out
        assert "- OPENAI_API_KEY" in out
        assert "- REDIS_URL" in out


class TestMissingExampleExitsOne:
    def test_no_example_file_returns_exit_failed(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env", "FOO=bar\n")
        code, _out, err = _run(["env-diff"], cwd=tmp_path)
        assert code == env_cmd.EXIT_FAILED
        assert ".env.example" in err


class TestIdenticalFilesExitsZeroWithMessage:
    def test_identical_variable_sets(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env", "FOO=1\nBAR=2\n")
        _write(tmp_path / ".env.example", "FOO=\nBAR=\n")
        code, out, _err = _run(["env-diff"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        assert "no differences" in out

    def test_env_missing_with_empty_example(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env.example", "")
        code, out, _err = _run(["env-diff"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        # Empty diff with no .env still mentions the example file count.
        assert "no diff" in out or "no differences" in out


class TestDotenvParser:
    def test_strips_comments_and_blank_lines(
        self,
        tmp_path: Path,
    ) -> None:
        contents = """\
        # A comment

        FOO=1

        # Another comment
        BAR=2
        """
        _write(tmp_path / ".env.example", contents.replace("        ", ""))
        names = env_cmd._parse_dotenv(tmp_path / ".env.example")
        assert names == ["FOO", "BAR"]

    def test_handles_export_prefix(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env.example", "export FOO=1\nexport BAR=2\n")
        names = env_cmd._parse_dotenv(tmp_path / ".env.example")
        assert names == ["FOO", "BAR"]

    def test_ignores_malformed_lines(
        self,
        tmp_path: Path,
    ) -> None:
        _write(
            tmp_path / ".env.example",
            "FOO=1\nnot a valid line\n=missing_name\n123BAD=skipped\nBAR=2\n",
        )
        names = env_cmd._parse_dotenv(tmp_path / ".env.example")
        # Only well-formed POSIX names survive.
        assert names == ["FOO", "BAR"]

    def test_preserves_declaration_order_and_dedupes(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env.example", "ZED=1\nALPHA=2\nZED=3\n")
        names = env_cmd._parse_dotenv(tmp_path / ".env.example")
        assert names == ["ZED", "ALPHA"]


class TestCIJSONOutput:
    def test_ci_payload_shape(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env", "EXTRA=1\n")
        _write(tmp_path / ".env.example", "EXTRA=\nMISSING=\n")
        code, out, _err = _run(["env-diff", "--ci"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        payload = json.loads(out)
        assert payload["schema_version"] == env_cmd.SCHEMA_VERSION
        assert payload["subcommand"] == "env:diff"
        assert payload["exit_code"] == env_cmd.EXIT_OK
        assert payload["env_present"] is True
        assert payload["adds"] == []
        assert payload["removes"] == ["MISSING"]

    def test_ci_payload_when_env_absent(
        self,
        tmp_path: Path,
    ) -> None:
        _write(tmp_path / ".env.example", "FOO=\n")
        code, out, _err = _run(["env-diff", "--ci"], cwd=tmp_path)
        assert code == env_cmd.EXIT_OK
        payload = json.loads(out)
        assert payload["env_present"] is False
        assert payload["removes"] == ["FOO"]
        assert payload["adds"] == []
