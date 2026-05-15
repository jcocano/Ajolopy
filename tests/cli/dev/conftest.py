"""Shared fixtures + helpers for ``ajolopy dev`` CLI tests.

The dev command's hot path is the resolution / banner / config-build
plumbing — none of that wants a live socket. The conftest provides:

- :func:`make_project` — drop a ``src/<package>/main.py`` skeleton
  under a fresh ``tmp_path`` so every detection branch is exercised
  in isolation.
- :func:`_StubServer` / :func:`stub_uvicorn` — patch the dev module's
  ``_make_server`` to capture the produced :class:`uvicorn.Config`
  without booting the network stack.
"""

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest


def make_project(
    tmp_path: Path,
    *,
    package: str = "myapp",
    main_body: str = "app = object()\n",
    extra_packages: tuple[str, ...] = (),
    create_main: bool = True,
    create_src: bool = True,
    create_env: bool = False,
) -> Path:
    """Build a minimal ``src/<pkg>/main.py`` layout under ``tmp_path``.

    Returns the project root (== ``tmp_path``). Callers pass that as
    ``cwd`` to :func:`ajolopy.cli.commands.dev._command`.
    """
    if create_src:
        src_dir = tmp_path / "src"
        src_dir.mkdir(exist_ok=True)
        pkg_dir = src_dir / package
        pkg_dir.mkdir(exist_ok=True)
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        if create_main:
            (pkg_dir / "main.py").write_text(
                textwrap.dedent(main_body),
                encoding="utf-8",
            )
        for extra in extra_packages:
            extra_dir = src_dir / extra
            extra_dir.mkdir(exist_ok=True)
            (extra_dir / "__init__.py").write_text("", encoding="utf-8")
    if create_env:
        (tmp_path / ".env").write_text("FOO=bar\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def project_factory() -> Any:
    """Return the :func:`make_project` helper as a fixture."""
    return make_project


class StubServer:
    """Stand-in for :class:`uvicorn.Server`.

    Records the :class:`uvicorn.Config` it was built with and
    short-circuits :meth:`run` so the dev command's tests never
    actually bind a socket.
    """

    instances: list[StubServer] = []

    def __init__(self, config: Any) -> None:
        self.config: Any = config
        self.run_called: bool = False
        StubServer.instances.append(self)

    def run(self) -> None:
        self.run_called = True


@pytest.fixture
def stub_uvicorn(monkeypatch: pytest.MonkeyPatch) -> type[StubServer]:
    """Patch ``dev._make_server`` so ``_command`` never blocks.

    Returns the stub class so tests can inspect ``StubServer.instances``
    after the call to assert against the recorded
    :class:`uvicorn.Config`.
    """
    from ajolopy.cli.commands import dev as dev_cmd

    StubServer.instances = []

    def _factory(config: Any) -> StubServer:
        return StubServer(config)

    monkeypatch.setattr(dev_cmd, "_make_server", _factory)
    return StubServer


@pytest.fixture(autouse=True)
def _cleanup_imported_modules() -> Any:  # pyright: ignore[reportUnusedFunction]
    """Drop any test-imported user modules so autodetect re-imports cleanly."""
    snapshot = set(sys.modules.keys())
    yield
    leaked = set(sys.modules.keys()) - snapshot
    for name in leaked:
        if name.startswith(("myapp", "myapp2", "altpkg", "noappapp")):
            sys.modules.pop(name, None)
