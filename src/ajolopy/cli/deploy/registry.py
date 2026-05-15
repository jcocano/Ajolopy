"""Module-level deploy-target registry.

The registry is an ordered dict keyed by :attr:`DeployTarget.name`.
``register_target`` overrides any earlier registration for the same
name — that is the seam AJ-42 / AJ-43 / AJ-44 / AJ-45 use to replace
the in-tree stubs with real implementations: each owning module simply
calls ``register_target(<RealTarget>())`` at import time, and the
last-write-wins semantics promote it without anyone touching this
file.
"""

from typing import TYPE_CHECKING

from .errors import DeployTargetNotFoundError

if TYPE_CHECKING:
    from .base import DeployTarget

_REGISTRY: dict[str, DeployTarget] = {}


def register_target(target: DeployTarget) -> None:
    """Register ``target`` under :attr:`DeployTarget.name`.

    Replaces any earlier registration for the same name. Order of
    *first* registration is preserved so ``--help`` lists targets in
    the order modules import them.
    """
    _REGISTRY[target.name] = target


def get_target(name: str) -> DeployTarget:
    """Return the target registered under ``name``.

    Raises :class:`DeployTargetNotFoundError` (with the list of known names)
    when nothing matches.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise DeployTargetNotFoundError(
            f"ajolopy deploy: unknown target {name!r}. Known targets: {known}.",
        ) from None


def list_targets() -> list[DeployTarget]:
    """Return every registered target in registration order."""
    return list(_REGISTRY.values())


def _clear_registry_for_tests() -> None:
    """Test-only helper.

    The registry is module-level state. Tests that exercise the
    public API in isolation can call this to start from an empty
    slate. NOT exported by ``__init__`` — import via the module path.
    """
    _REGISTRY.clear()


__all__ = ["_clear_registry_for_tests", "get_target", "list_targets", "register_target"]
