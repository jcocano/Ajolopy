"""Shared fixtures and helpers for the ``ajolopy env:*`` CLI tests.

Each test builds a tiny fake project under ``tmp_path`` containing a
single Python package (default ``myapp``) with an ``app_module.py``
that declares a ``BaseConfig`` subclass with the fields the test
cares about. The fixtures keep the helper surface tight so a
regression in any one branch points at the broken file directly.
"""

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

# Module names tests are allowed to create inside ``src/`` — the
# autouse cleanup below drops any leak from ``sys.modules`` after each
# test so import-cache state does not bleed between cases.
_TEST_PACKAGE_NAMES: tuple[str, ...] = (
    "myapp",
    "myapp2",
    "altpkg",
    "envapp",
    "envapp2",
    "secretapp",
    "diffapp",
    "validateapp",
    "invalidapp",
    "fallbackapp",
)


def make_project(
    tmp_path: Path,
    *,
    package: str = "myapp",
    config_body: str | None = None,
    in_app_module: bool = True,
    create_app_module: bool = True,
    extra_packages: tuple[str, ...] = (),
) -> Path:
    """Build a minimal ``src/<package>/app_module.py`` layout.

    ``config_body`` is dedented and dropped into ``app_module.py`` when
    ``in_app_module=True``; otherwise it is written to a sibling
    ``config.py`` and ``app_module.py`` is left as an empty stub. When
    ``create_app_module`` is ``False``, the ``app_module.py`` file is
    skipped entirely so the discovery fallback can be exercised.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    pkg_dir = src_dir / package
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

    body = textwrap.dedent(config_body) if config_body is not None else ""

    if in_app_module:
        if create_app_module:
            (pkg_dir / "app_module.py").write_text(body, encoding="utf-8")
    else:
        if create_app_module:
            (pkg_dir / "app_module.py").write_text("", encoding="utf-8")
        # The fallback path imports ``<package>`` directly; emit the
        # config there so ``BaseConfig`` is discoverable when
        # ``app_module`` is empty.
        init_path = pkg_dir / "__init__.py"
        init_path.write_text(body, encoding="utf-8")

    for extra in extra_packages:
        extra_dir = src_dir / extra
        extra_dir.mkdir(exist_ok=True)
        (extra_dir / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def project_factory() -> Any:
    """Return :func:`make_project` as a fixture."""
    return make_project


@pytest.fixture(autouse=True)
def _cleanup_imported_modules() -> Any:  # pyright: ignore[reportUnusedFunction]
    """Drop any test-imported user modules so each test imports cleanly."""
    snapshot = set(sys.modules.keys())
    yield
    leaked = set(sys.modules.keys()) - snapshot
    for name in leaked:
        for prefix in _TEST_PACKAGE_NAMES:
            if name == prefix or name.startswith(prefix + "."):
                sys.modules.pop(name, None)
                break


@pytest.fixture(autouse=True)
def _cleanup_syspath(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Snapshot ``sys.path`` so a test's ``src/`` insertion never leaks."""
    original = list(sys.path)
    monkeypatch.setattr(sys, "path", original.copy())


SAMPLE_CONFIG = """
from ajolopy.config import BaseConfig


class AppConfig(BaseConfig):
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str | None = None
    APP_ENV: str = "development"
    LOG_LEVEL: str = "info"
"""
