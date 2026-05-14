"""``UseGuards`` is exported from the top-level package and from ``ajolopy.guards``."""

import ajolopy
from ajolopy.guards import (
    BearerTokenGuard,
    Guard,
    GuardError,
    GuardForbiddenError,
    GuardUnauthorizedError,
    IPAllowlistGuard,
    UseGuards,
    UseGuardsConfigError,
)

# Alias via attribute access to avoid mixing ``import ajolopy`` with
# ``from ajolopy import guards``. CodeQL flags both as importing the
# same module under two styles even when the names differ.
ajolopy_guards = ajolopy.guards


class TestPublicExports:
    def test_top_level_import(self) -> None:
        assert ajolopy.UseGuards is UseGuards

    def test_top_level_all(self) -> None:
        assert "UseGuards" in ajolopy.__all__

    def test_guards_package_exports(self) -> None:
        expected = {
            "Guard",
            "GuardError",
            "GuardForbiddenError",
            "GuardUnauthorizedError",
            "BearerTokenGuard",
            "IPAllowlistGuard",
            "UseGuards",
            "UseGuardsConfigError",
        }
        assert expected.issubset(set(ajolopy_guards.__all__))

    def test_error_hierarchy(self) -> None:
        assert issubclass(GuardUnauthorizedError, GuardError)
        assert issubclass(GuardForbiddenError, GuardError)
        assert issubclass(UseGuardsConfigError, GuardError)

    def test_builtins_extend_guard(self) -> None:
        assert issubclass(BearerTokenGuard, Guard)
        assert issubclass(IPAllowlistGuard, Guard)
