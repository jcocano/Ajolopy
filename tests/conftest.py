"""Repo-wide pytest fixtures.

The provider registry holds process-wide state (registered LLMProvider
classes + routing rules). Provider packages register themselves on import
as a side effect, so tests that import any of them transitively can mutate
this state. This fixture snapshots both tables before every test, clears
``_PROVIDERS`` to a known-empty baseline so each test starts deterministic,
and restores the original state on exit. ``_ROUTES`` keeps the built-in
defaults during the test so prefix routing works without setup.
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
