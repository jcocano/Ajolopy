"""``ajolopy mcp-serve`` CLI: argument parsing, target resolution, exit codes.

The real ``mcp.server.stdio.stdio_server`` machinery is only exercised
once (``test_runs_stdio_target_with_eof_to_clean_shutdown``); every
other test stops short of the SDK by monkey-patching ``run_stdio`` so
the suite stays fast and SDK-free.
"""

import sys
from typing import TYPE_CHECKING

import pytest

import ajolopy
from ajolopy.cli import main as cli_main
from ajolopy.cli.commands import mcp_serve as mcp_serve_cmd

MCPServer = ajolopy.MCPServer
Tool = ajolopy.Tool

if TYPE_CHECKING:
    pass


def _call_main(argv: list[str]) -> int:
    """Invoke the CLI entry, normalising ``SystemExit`` to an int code."""
    try:
        return cli_main(argv)
    except SystemExit as exc:
        # argparse raises SystemExit on usage errors with an int code.
        if isinstance(exc.code, int):
            return exc.code
        return mcp_serve_cmd.EXIT_USAGE


class TestRootHelp:
    def test_root_help_lists_mcp_serve(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = _call_main(["--help"])
        captured = capsys.readouterr()
        assert code == 0
        assert "mcp-serve" in captured.out

    def test_mcp_serve_help_mentions_target_form(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = _call_main(["mcp-serve", "--help"])
        captured = capsys.readouterr()
        assert code == 0
        assert "package.module:ClassName" in captured.out


class TestTargetParsing:
    def test_malformed_target_exits_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = _call_main(["mcp-serve", "invalid-target-format"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_USAGE
        assert "expected 'package.module:ClassName' format" in captured.out

    def test_empty_module_exits_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = _call_main(["mcp-serve", ":SomeClass"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_USAGE
        assert "missing either the module or the class name" in captured.out

    def test_empty_class_exits_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = _call_main(["mcp-serve", "package:"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_USAGE
        assert "missing either the module or the class name" in captured.out


class TestImportFailures:
    def test_module_not_found_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = _call_main(["mcp-serve", "no_such_module_xyz:Anything"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_IMPORT_ERROR
        assert "module not found" in captured.out

    def test_attribute_not_found_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code = _call_main(["mcp-serve", "ajolopy:NoSuchClass"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_TARGET_NOT_FOUND
        assert "attribute not found" in captured.out


# Mounted on the ``ajolopy`` package so the CLI can ``getattr`` the
# class without us creating an actual file. Both classes are stamped
# at import time of this test module.


@MCPServer(transport="stdio")
class _GoodStdioCLI:
    @Tool
    def ping(self) -> str:
        return "pong"


@MCPServer(transport="http", path="/mcp")
class _HttpOnlyCLI:
    @Tool
    def ping(self) -> str:
        return "pong"


class _NotAnMCPServer:
    @Tool
    def ping(self) -> str:
        return "pong"


# Register the three test targets under the ``ajolopy`` package so the
# CLI can resolve them via ``getattr``.
ajolopy._GoodStdioCLI = _GoodStdioCLI  # type: ignore[attr-defined]
ajolopy._HttpOnlyCLI = _HttpOnlyCLI  # type: ignore[attr-defined]
ajolopy._NotAnMCPServer = _NotAnMCPServer  # type: ignore[attr-defined]


class TestTargetValidation:
    def test_target_missing_decorator_exits_not_stdio(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code = _call_main(["mcp-serve", "ajolopy:_NotAnMCPServer"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_NOT_STDIO_SERVER
        assert "not decorated with @MCPServer" in captured.out

    def test_target_http_transport_exits_not_stdio(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code = _call_main(["mcp-serve", "ajolopy:_HttpOnlyCLI"])
        captured = capsys.readouterr()
        assert code == mcp_serve_cmd.EXIT_NOT_STDIO_SERVER
        assert "transport='http'" in captured.out


class TestStdioBoot:
    def test_runs_stdio_target_calling_run_stdio_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Wire a fake ``run_stdio`` to verify the CLI reaches the boot path."""
        calls: list[object] = []

        async def fake_run_stdio(runtime: object) -> None:
            calls.append(runtime)

        monkeypatch.setattr(mcp_serve_cmd, "run_stdio", fake_run_stdio)
        code = _call_main(["mcp-serve", "ajolopy:_GoodStdioCLI"])
        assert code == mcp_serve_cmd.EXIT_OK
        assert len(calls) == 1

    def test_runs_stdio_target_with_real_sdk_eof(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drive the real ``stdio_server`` with an immediate-EOF stdin.

        The reader sees no JSON-RPC bytes, closes the memory object
        stream, and ``Server.run`` unblocks. The CLI should return 0.
        """
        from io import BytesIO, TextIOWrapper

        # Replace stdin / stdout with in-memory streams so the SDK does
        # not try to read the real terminal.
        fake_stdin = TextIOWrapper(BytesIO(b""), encoding="utf-8")
        fake_stdout = TextIOWrapper(BytesIO(), encoding="utf-8")
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        monkeypatch.setattr(sys, "stdout", fake_stdout)
        # ``stdio_server`` reads from sys.stdin.buffer / sys.stdout.buffer.
        # The wrappers above expose ``.buffer`` automatically.
        code = _call_main(["mcp-serve", "ajolopy:_GoodStdioCLI"])
        assert code == mcp_serve_cmd.EXIT_OK
