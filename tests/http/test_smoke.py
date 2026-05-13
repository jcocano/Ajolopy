"""Smoke test for the HTTP layer package skeleton.

Ensures the public ``ajolopy.http`` module imports cleanly and exposes the
configuration errors used by the rest of the layer. The full surface (app
factory, markers, filters, exceptions) is exercised by the per-concern
test files added alongside their implementations.
"""

import ajolopy.http as http_pkg


def test_http_package_exports_errors():
    assert issubclass(http_pkg.HttpHandlerConfigError, http_pkg.HttpLayerError)
    assert issubclass(http_pkg.ExceptionFilterConfigError, http_pkg.HttpLayerError)
    assert issubclass(http_pkg.HttpLayerError, RuntimeError)


def test_http_package_all_is_complete():
    for name in http_pkg.__all__:
        assert hasattr(http_pkg, name), f"{name} declared in __all__ but missing"
