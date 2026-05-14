"""Repo-wide pytest fixtures.

The provider registry holds process-wide state (registered LLMProvider
classes + routing rules). Provider packages register themselves on import
as a side effect, so tests that import any of them transitively can mutate
this state. This fixture snapshots both tables before every test, clears
``_PROVIDERS`` to a known-empty baseline so each test starts deterministic,
and restores the original state on exit. ``_ROUTES`` keeps the built-in
defaults during the test so prefix routing works without setup.

The MCP registry is process-wide too; ``reset_mcp_registry_autouse``
replaces the singleton between tests so per-test MCP class registrations
never leak.

``patch_client_builder`` lives here (rather than under ``tests/mcp/``) so
agent and workflow cross-cut tests can install a custom client factory
without importing ``tests.mcp.conftest`` directly.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from ajolopy.mcp import reset_mcp_registry
from ajolopy.mcp.client import MCPClient
from ajolopy.mcp.spec import Transport
from ajolopy.providers import registry

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def isolate_registry() -> Iterator[None]:
    saved_providers = registry._PROVIDERS.copy()
    saved_routes = list(registry._ROUTES)
    registry._PROVIDERS.clear()
    registry._ROUTES.clear()
    registry._ROUTES.extend(registry._DEFAULT_ROUTES)
    try:
        yield
    finally:
        registry._PROVIDERS.clear()
        registry._PROVIDERS.update(saved_providers)
        registry._ROUTES.clear()
        registry._ROUTES.extend(saved_routes)


@pytest.fixture(autouse=True)
def reset_mcp_registry_autouse() -> Iterator[None]:
    """Replace the process-wide :class:`MCPRegistry` between tests."""
    reset_mcp_registry()
    yield
    reset_mcp_registry()


@pytest.fixture
def patch_client_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[str, Transport, dict[str, Any] | None], MCPClient]], None]:
    """Patch :func:`ajolopy.mcp.registry.build_builtin_client` for one test.

    Returns a callable the test invokes with a factory ``(spec_str,
    transport, auth) -> MCPClient``. Every connect attempt during the
    test routes through that factory, so no real MCP SDK import is
    needed.
    """

    def _install(factory: Callable[[str, Transport, dict[str, Any] | None], MCPClient]) -> None:
        from ajolopy.mcp import registry as registry_module

        def _builder(
            spec_str: str,
            *,
            transport: Transport,
            auth: dict[str, Any] | None,
        ) -> MCPClient:
            return factory(spec_str, transport, auth)

        monkeypatch.setattr(registry_module, "build_builtin_client", _builder)

    return _install
