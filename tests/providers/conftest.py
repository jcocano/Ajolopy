"""Shared fixtures for provider tests.

The provider registry holds process-wide state (registered classes + routing
rules). Tests that mutate that state must not leak into other tests, so this
fixture snapshots both tables before each test and restores them after.
"""

from typing import TYPE_CHECKING

import pytest

from ajolopy.providers import registry

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def isolate_registry() -> Iterator[None]:
    saved_providers = registry._PROVIDERS.copy()
    saved_routes = list(registry._ROUTES)
    # Each test starts from a fresh _PROVIDERS table so a previous test
    # (or a side-effect import like ajolopy.providers.anthropic) can't leak
    # an existing registration into a test that expects empty state.
    # _ROUTES keeps the built-in defaults so prefix routing works.
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
