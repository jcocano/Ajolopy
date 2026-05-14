"""``@UseGuards`` primitive — declarative HTTP route gating.

Public surface — the :func:`UseGuards` decorator, the :class:`Guard`
ABC, the two built-in guards, the error hierarchy, and the mount-layer
helpers (:func:`apply_guard_chain`, :func:`resolve_guard_chain`)
consumed by :mod:`ajolopy.routes` and :mod:`ajolopy.stream`.

Importing this package is import-clean and has no third-party
runtime dependencies — :class:`IPAllowlistGuard` parses CIDRs via the
stdlib :mod:`ipaddress` module.
"""

from .base import Guard, GuardLike
from .builtins import BearerTokenGuard, IPAllowlistGuard
from .decorator import GUARDS_META_ATTR, UseGuards, get_guard_chain
from .errors import (
    GuardError,
    GuardForbiddenError,
    GuardUnauthorizedError,
    UseGuardsConfigError,
)
from .runtime import apply_guard_chain, resolve_guard_chain

__all__ = [
    "GUARDS_META_ATTR",
    "BearerTokenGuard",
    "Guard",
    "GuardError",
    "GuardForbiddenError",
    "GuardLike",
    "GuardUnauthorizedError",
    "IPAllowlistGuard",
    "UseGuards",
    "UseGuardsConfigError",
    "apply_guard_chain",
    "get_guard_chain",
    "resolve_guard_chain",
]
