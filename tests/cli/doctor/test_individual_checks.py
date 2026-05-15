"""Per-check pass/fail/skip paths for ``ajolopy doctor``.

Each check class is exercised in isolation so a regression points at
exactly one source line. Network-touching checks (provider health +
OTel endpoint + MCP) are driven through mocks that simulate every
documented outcome: success, failure, timeout, missing dependency.
"""

import asyncio
import socket
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ajolopy.cli.commands import doctor as doctor_cmd
from ajolopy.cli.commands.doctor import (
    AjolopyInstalledCheck,
    EnvFilePresentCheck,
    EnvValidationCheck,
    MCPServersCheck,
    OtelEndpointCheck,
    ProjectStructureCheck,
    ProviderHealthCheck,
    PyprojectPresentCheck,
    PythonVersionCheck,
    VenvPresentCheck,
)

# ---------------------------------------------------------------------------
# 1. PythonVersionCheck
# ---------------------------------------------------------------------------


class TestPythonVersionCheck:
    async def test_pass_on_supported_version(self) -> None:
        check = PythonVersionCheck()
        passed, message = await check.run()
        assert passed is True
        assert message.startswith("Python ")
        assert sys.version_info[:2] >= (3, 14)

    async def test_fail_when_simulated_older(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Patch ``sys.version_info`` to look like Python 3.13 so the failure
        # branch is reachable without spawning a different interpreter.
        from types import SimpleNamespace

        fake = SimpleNamespace(major=3, minor=13, micro=2)
        monkeypatch.setattr("ajolopy.cli.commands.doctor.sys.version_info", fake)
        check = PythonVersionCheck()
        passed, message = await check.run()
        assert passed is False
        assert "3.13.2" in message
        assert "< 3.14" in message


# ---------------------------------------------------------------------------
# 2. AjolopyInstalledCheck
# ---------------------------------------------------------------------------


class TestAjolopyInstalledCheck:
    async def test_pass_reports_version(self) -> None:
        check = AjolopyInstalledCheck()
        passed, message = await check.run()
        assert passed is True
        assert message.startswith("version ")

    async def test_fail_when_import_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_name: str) -> Any:
            raise ImportError("simulated")

        monkeypatch.setattr("ajolopy.cli.commands.doctor.importlib.import_module", _raise)
        check = AjolopyInstalledCheck()
        passed, message = await check.run()
        assert passed is False
        assert "simulated" in message


# ---------------------------------------------------------------------------
# 3. VenvPresentCheck
# ---------------------------------------------------------------------------


class TestVenvPresentCheck:
    async def test_pass_when_dotvenv_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".venv").mkdir()
        check = VenvPresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is True
        assert ".venv" in message

    async def test_pass_when_virtual_env_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VIRTUAL_ENV", "/opt/venv")
        check = VenvPresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is True
        assert "/opt/venv" in message

    async def test_warn_when_neither_present(self, tmp_path: Path) -> None:
        check = VenvPresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is None
        assert "VIRTUAL_ENV not set" in message


# ---------------------------------------------------------------------------
# 4. PyprojectPresentCheck
# ---------------------------------------------------------------------------


class TestPyprojectPresentCheck:
    async def test_pass_when_pyproject_present(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
        check = PyprojectPresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is True
        assert "pyproject.toml" in message

    async def test_fail_when_pyproject_missing(self, tmp_path: Path) -> None:
        check = PyprojectPresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is False
        assert "pyproject.toml" in message


# ---------------------------------------------------------------------------
# 5. ProjectStructureCheck
# ---------------------------------------------------------------------------


class TestProjectStructureCheck:
    async def test_pass_when_src_pkg_main_exists(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "myapp"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "main.py").write_text("app = object()\n", encoding="utf-8")
        check = ProjectStructureCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is True
        assert "src/myapp/main.py" in message

    async def test_fail_when_src_missing(self, tmp_path: Path) -> None:
        check = ProjectStructureCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is False
        assert "src/" in message

    async def test_fail_when_no_package_under_src(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        check = ProjectStructureCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is False
        assert "no package under src/" in message

    async def test_fail_when_pkg_lacks_main(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "myapp"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        check = ProjectStructureCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is False
        assert "main.py not found" in message


# ---------------------------------------------------------------------------
# 6. EnvFilePresentCheck
# ---------------------------------------------------------------------------


class TestEnvFilePresentCheck:
    async def test_pass_when_dotenv_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
        check = EnvFilePresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is True
        assert message == ".env"

    async def test_warn_when_dotenv_missing(self, tmp_path: Path) -> None:
        check = EnvFilePresentCheck(cwd=tmp_path)
        passed, message = await check.run()
        assert passed is None
        assert "using defaults" in message


# ---------------------------------------------------------------------------
# 7. EnvValidationCheck
# ---------------------------------------------------------------------------


class TestEnvValidationCheck:
    async def test_pass_against_bare_baseconfig(self) -> None:
        check = EnvValidationCheck()
        passed, message = await check.run()
        assert passed is True
        assert "vars OK" in message


# ---------------------------------------------------------------------------
# 8-10. ProviderHealthCheck (Anthropic / OpenAI / Gemini share one class)
# ---------------------------------------------------------------------------


def _make_provider_check() -> ProviderHealthCheck:
    return ProviderHealthCheck(
        name="anthropic_api_key",
        env_var="ANTHROPIC_API_KEY",
        module_path="ajolopy.providers.anthropic",
        class_name="AnthropicProvider",
    )


class TestProviderHealthCheck:
    async def test_skip_when_env_var_missing(self) -> None:
        # clean_env autouse fixture has stripped every key already.
        check = _make_provider_check()
        passed, message = await check.run()
        assert passed is None
        assert "not configured" in message

    async def test_pass_when_health_check_succeeds(
        self,
        with_anthropic_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del with_anthropic_key

        async def _ok(self: object) -> None:
            del self

        from ajolopy.providers.anthropic import AnthropicProvider

        monkeypatch.setattr(AnthropicProvider, "health_check", _ok)
        check = _make_provider_check()
        passed, message = await check.run()
        assert passed is True
        assert message == "reachable"

    async def test_warn_when_health_check_raises(
        self,
        with_anthropic_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del with_anthropic_key

        async def _boom(self: object) -> None:
            del self
            raise RuntimeError("upstream 503")

        from ajolopy.providers.anthropic import AnthropicProvider

        monkeypatch.setattr(AnthropicProvider, "health_check", _boom)
        check = _make_provider_check()
        passed, message = await check.run()
        # Network errors must downgrade to warn so doctor never aborts.
        assert passed is None
        assert "upstream 503" in message

    async def test_warn_when_health_check_times_out(
        self,
        with_anthropic_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del with_anthropic_key

        async def _hang(self: object) -> None:
            del self
            await asyncio.sleep(10)

        from ajolopy.providers.anthropic import AnthropicProvider

        monkeypatch.setattr(AnthropicProvider, "health_check", _hang)
        # Shrink the timeout so the test is fast.
        monkeypatch.setattr(doctor_cmd, "_NETWORK_TIMEOUT_S", 0.05)
        check = _make_provider_check()
        passed, message = await check.run()
        assert passed is None
        assert "timed out" in message

    async def test_fail_when_constructor_raises(
        self,
        with_anthropic_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Construction errors should be a hard fail — they signal a code
        # problem (missing SDK / mis-wired DI), not a network blip.
        del with_anthropic_key

        from ajolopy.providers.anthropic import AnthropicProvider

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated init failure")

        monkeypatch.setattr(AnthropicProvider, "__init__", _boom)
        check = _make_provider_check()
        passed, message = await check.run()
        assert passed is False
        assert "simulated init failure" in message


# ---------------------------------------------------------------------------
# 11. OtelEndpointCheck
# ---------------------------------------------------------------------------


class TestOtelEndpointCheck:
    async def test_warn_when_endpoint_unset(self) -> None:
        check = OtelEndpointCheck()
        passed, message = await check.run()
        assert passed is None
        assert "not set" in message

    async def test_pass_when_endpoint_reachable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

        def _ok(*_args: Any, **_kwargs: Any) -> MagicMock:
            sock = MagicMock()
            sock.__enter__ = MagicMock(return_value=sock)
            sock.__exit__ = MagicMock(return_value=False)
            return sock

        monkeypatch.setattr(socket, "create_connection", _ok)
        check = OtelEndpointCheck()
        passed, message = await check.run()
        assert passed is True
        assert "reachable" in message

    async def test_warn_when_endpoint_unreachable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise ConnectionRefusedError("simulated")

        monkeypatch.setattr(socket, "create_connection", _boom)
        check = OtelEndpointCheck()
        passed, message = await check.run()
        assert passed is None
        assert "unreachable" in message

    async def test_warn_when_endpoint_unparseable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # "://" with no host triggers the parse-fail branch.
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://")
        check = OtelEndpointCheck()
        passed, message = await check.run()
        assert passed is None
        assert "could not be parsed" in message


# ---------------------------------------------------------------------------
# 12. MCPServersCheck
# ---------------------------------------------------------------------------


class TestMCPServersCheck:
    async def test_skip_when_no_mcp_classes(self, mcp_registry_reset: Any) -> None:
        del mcp_registry_reset
        check = MCPServersCheck()
        passed, message = await check.run()
        assert passed is None
        assert "no @MCP classes" in message

    async def test_pass_when_every_class_connects(
        self,
        mcp_registry_reset: Any,
    ) -> None:
        # Stamp two classes onto the registry by hand so we do not need
        # the @MCP decorator's validation logic for this test.
        from ajolopy.mcp.registry import ServerEntry

        class A:
            pass

        class B:
            pass

        mcp_registry_reset.register_class(A, entries=[], timeout=5.0)
        mcp_registry_reset.register_class(B, entries=[], timeout=5.0)

        # Replace ``connect_all_for`` with a no-op so we exercise the
        # success path without opening real sockets. ``ServerEntry`` is
        # imported only to keep the symbol referenced if pyright walks
        # the module — the test does not need an instance.
        del ServerEntry

        async def _noop(cls: object) -> None:
            del cls

        mcp_registry_reset.connect_all_for = _noop

        check = MCPServersCheck()
        passed, message = await check.run()
        assert passed is True
        assert "2 @MCP class(es) reachable" in message

    async def test_warn_when_class_raises(self, mcp_registry_reset: Any) -> None:
        class A:
            pass

        mcp_registry_reset.register_class(A, entries=[], timeout=5.0)

        async def _boom(cls: object) -> None:
            del cls
            raise RuntimeError("simulated mcp failure")

        mcp_registry_reset.connect_all_for = _boom

        check = MCPServersCheck()
        passed, message = await check.run()
        assert passed is None
        assert "simulated mcp failure" in message

    async def test_warn_when_class_times_out(
        self,
        mcp_registry_reset: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class A:
            pass

        mcp_registry_reset.register_class(A, entries=[], timeout=5.0)

        async def _hang(cls: object) -> None:
            del cls
            await asyncio.sleep(10)

        mcp_registry_reset.connect_all_for = _hang
        monkeypatch.setattr(doctor_cmd, "_NETWORK_TIMEOUT_S", 0.05)

        check = MCPServersCheck()
        passed, message = await check.run()
        assert passed is None
        assert "timeout" in message


# ---------------------------------------------------------------------------
# Helpers — exercise the OTel endpoint parser directly because the parse
# branches are a frequent source of regressions.
# ---------------------------------------------------------------------------


class TestParseOtelEndpoint:
    def test_http_scheme_default_port_80(self) -> None:
        host, port = doctor_cmd._parse_otel_endpoint("http://example.com")
        assert host == "example.com"
        assert port == 80

    def test_https_scheme_default_port_443(self) -> None:
        host, port = doctor_cmd._parse_otel_endpoint("https://example.com")
        assert host == "example.com"
        assert port == 443

    def test_explicit_port_wins(self) -> None:
        host, port = doctor_cmd._parse_otel_endpoint("http://example.com:4318/v1/traces")
        assert host == "example.com"
        assert port == 4318

    def test_bare_host_port(self) -> None:
        host, port = doctor_cmd._parse_otel_endpoint("collector.internal:4317")
        assert host == "collector.internal"
        assert port == 4317

    def test_empty_returns_none(self) -> None:
        host, _ = doctor_cmd._parse_otel_endpoint("")
        assert host is None

    def test_garbage_port_returns_none(self) -> None:
        host, _ = doctor_cmd._parse_otel_endpoint("host:not-a-number")
        assert host is None


# ---------------------------------------------------------------------------
# Smoke: ProviderHealthCheck handles a missing module gracefully (skip).
# ---------------------------------------------------------------------------


class TestProviderHealthMissingModule:
    async def test_skip_when_module_path_unknown(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force ImportError on the dotted path. We capture the stdlib's
        # ``import_module`` directly so the patched wrapper can still
        # delegate for every other dotted path the check might touch.
        import importlib

        original = importlib.import_module

        def _fail(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "ajolopy.providers.nonexistent":
                raise ImportError("simulated")
            return original(name, *args, **kwargs)

        monkeypatch.setattr("ajolopy.cli.commands.doctor.importlib.import_module", _fail)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
        check = ProviderHealthCheck(
            name="anthropic_api_key",
            env_var="ANTHROPIC_API_KEY",
            module_path="ajolopy.providers.nonexistent",
            class_name="Foo",
        )
        passed, message = await check.run()
        assert passed is None
        assert "not importable" in message


# ---------------------------------------------------------------------------
# Sanity: each provider's concrete ``health_check`` calls the documented
# cheapest network shape. We only need to confirm the SDK seam, not what
# the SDK actually returns.
# ---------------------------------------------------------------------------


class TestConcreteHealthChecks:
    async def test_anthropic_health_check_calls_models_list(
        self,
        with_anthropic_key: str,
    ) -> None:
        del with_anthropic_key
        from ajolopy.providers.anthropic import AnthropicProvider

        list_mock = AsyncMock(return_value=None)
        client = MagicMock()
        client.models.list = list_mock
        provider = AnthropicProvider(client=client)
        await provider.health_check()
        list_mock.assert_awaited_once()

    async def test_openai_health_check_calls_models_list(
        self,
        with_openai_key: str,
    ) -> None:
        del with_openai_key
        from ajolopy.providers.openai import OpenAIProvider

        list_mock = AsyncMock(return_value=None)
        client = MagicMock()
        client.models.list = list_mock
        provider = OpenAIProvider(client=client)
        await provider.health_check()
        list_mock.assert_awaited_once()

    async def test_gemini_health_check_iterates_models_list(
        self,
        with_gemini_key: str,
    ) -> None:
        del with_gemini_key
        from ajolopy.providers.gemini import GeminiProvider

        # ``aio.models.list`` returns an async iterator; we yield one
        # item so the loop pulls a single page and exits.
        class _Iter:
            def __init__(self) -> None:
                self._yielded = False

            def __aiter__(self) -> _Iter:
                return self

            async def __anext__(self) -> Any:
                if self._yielded:
                    raise StopAsyncIteration
                self._yielded = True
                return MagicMock()

        client = MagicMock()
        # GeminiProvider uses ``self._aio_models.list()`` via a cast; the
        # property returns ``client.aio.models`` cast to ``Any``. We attach
        # the iterator to that attribute path so the check exercises it
        # without any extra plumbing.
        client.aio.models.list = MagicMock(return_value=_Iter())
        provider = GeminiProvider(client=client)
        await provider.health_check()
        client.aio.models.list.assert_called_once()

    async def test_anthropic_health_check_wraps_sdk_errors(
        self,
        with_anthropic_key: str,
    ) -> None:
        del with_anthropic_key
        import anthropic

        from ajolopy.providers.anthropic import AnthropicProvider, AnthropicProviderError

        client = MagicMock()

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            # APIConnectionError is in the retriable tuple, so the
            # provider must rewrap it as AnthropicProviderError.
            raise anthropic.APIConnectionError(request=MagicMock())

        client.models.list = AsyncMock(side_effect=_boom)
        provider = AnthropicProvider(client=client)
        with pytest.raises(AnthropicProviderError):
            await provider.health_check()
