"""Regression test for AJ-80: built-in providers must auto-register on import.

Before the fix, importing ``ajolopy`` (or even ``ajolopy.providers``) did not
populate the provider registry, because each built-in provider's registration
side effect lives inside ``ajolopy.providers.<pkg>.__init__`` and nothing
imported those sibling packages eagerly. Users who followed the documented
quickstart (``from ajolopy import Agent; @Agent(model="claude-opus-4-7", ...)``)
hit ``ProviderNotRegisteredError`` at boot.

These tests pin the behaviour both ways: ``import ajolopy`` and
``import ajolopy.providers`` must each leave all four v0.1 built-in providers
registered.

The checks run in a subprocess on purpose. The repo-wide ``isolate_registry``
fixture in ``tests/conftest.py`` clears ``_PROVIDERS`` at the start of every
test, so the parent process always reports an empty registry regardless of
production behaviour. A fresh interpreter is the only honest way to observe
what happens on real ``import ajolopy``.
"""

import subprocess
import sys

_EXPECTED_KEYS = {"anthropic", "openai", "gemini", "universal-openai"}


def _fresh_registry_keys(import_target: str) -> set[str]:
    """Spawn a fresh Python process, import ``import_target``, return registry keys."""
    script = (
        f"import {import_target}\n"
        "from ajolopy.providers.registry import _PROVIDERS\n"
        "import sys\n"
        "sys.stdout.write(','.join(sorted(_PROVIDERS.keys())))\n"
    )
    # ``import_target`` is a constant inside this test module, never user input,
    # so the subprocess invocation is safe. S603 fires on every subprocess call.
    out = subprocess.check_output(  # noqa: S603
        [sys.executable, "-c", script], text=True
    )
    return set(out.split(",")) if out else set()


def test_top_level_import_registers_all_built_in_providers() -> None:
    keys = _fresh_registry_keys("ajolopy")
    assert _EXPECTED_KEYS.issubset(keys), (
        f"Fresh `import ajolopy` did not register all built-in providers. "
        f"Got {sorted(keys)!r}, expected superset of {sorted(_EXPECTED_KEYS)!r}."
    )


def test_providers_package_import_registers_all_built_in_providers() -> None:
    keys = _fresh_registry_keys("ajolopy.providers")
    assert _EXPECTED_KEYS.issubset(keys), (
        f"Fresh `import ajolopy.providers` did not register all built-in "
        f"providers. Got {sorted(keys)!r}, expected superset of "
        f"{sorted(_EXPECTED_KEYS)!r}."
    )
