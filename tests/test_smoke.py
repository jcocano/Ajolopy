"""Smoke test — keeps CI green from day 1, replaced with real tests as primitives land."""

import ajolopy


def test_package_imports() -> None:
    assert ajolopy.__version__
