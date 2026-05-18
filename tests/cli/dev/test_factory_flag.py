"""Regression tests for AJ-91 — `factory=True` propagation.

The dev command must inspect the resolved target after import and pass
``factory=True`` to :class:`uvicorn.Config` whenever the user's
``app`` attribute is an ``async def`` zero-arg coroutine factory. The
scaffold + every shipped example expose ``app`` this way:

```python
async def app() -> object:
    return await AjolopyFactory.create(AppModule)
```

Without the flag uvicorn auto-detects the factory but logs a
"WARNING: ASGI app factory detected" line on every boot. Cosmetic but
visible — these tests pin both branches (coroutine factory vs. plain
ASGI callable) so a regression flips one assertion immediately.
"""

import io
import sys
from pathlib import Path
from typing import Any

import pytest

from ajolopy.cli.commands import dev as dev_cmd
from ajolopy.cli.dispatcher import build_parser


def _run(
    argv: list[str],
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    """Drive ``_command`` with StringIO buffers; return (code, out, err)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = dev_cmd._command(args, stdout=stdout, stderr=stderr, cwd=cwd)
    return code, stdout.getvalue(), stderr.getvalue()


def _install_module(tmp_path: Path, name: str, body: str) -> None:
    """Drop ``<name>.py`` under ``tmp_path`` and prepend it to sys.path."""
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))


@pytest.fixture(autouse=True)
def _scrub_sys_path() -> Any:  # pyright: ignore[reportUnusedFunction]
    """Restore ``sys.path`` + drop test-imported modules between cases."""
    original = list(sys.path)
    snapshot = set(sys.modules.keys())
    yield
    sys.path[:] = original
    for name in set(sys.modules.keys()) - snapshot:
        sys.modules.pop(name, None)


class TestFactoryFlagAutodetect:
    def test_async_factory_target_sets_factory_true(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        """Auto-detected ``app`` defined with ``async def`` -> factory=True."""
        project_factory(
            tmp_path,
            package="myapp",
            main_body="async def app() -> object:\n    return object()\n",
        )

        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.factory is True

    def test_plain_asgi_app_keeps_factory_false(
        self,
        tmp_path: Path,
        project_factory: Any,
        stub_uvicorn: Any,
    ) -> None:
        """Pre-built ASGI app (plain callable) keeps ``factory=False``."""
        project_factory(
            tmp_path,
            package="myapp",
            main_body="app = object()\n",
        )

        code, _out, err = _run(["dev", "--no-reload"], cwd=tmp_path)

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.factory is False


class TestFactoryFlagExplicitOverride:
    def test_async_factory_via_app_flag_sets_factory_true(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        """``--app module:var`` pointed at a coroutine -> factory=True."""
        _install_module(
            tmp_path,
            "explicit_factory",
            "async def app() -> object:\n    return object()\n",
        )

        code, _out, err = _run(
            ["dev", "--app", "explicit_factory:app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.factory is True

    def test_plain_object_app_keeps_factory_false(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        """A pre-built ASGI app instance keeps ``factory=False``."""
        _install_module(
            tmp_path,
            "explicit_plain",
            "app = object()\n",
        )

        code, _out, err = _run(
            ["dev", "--app", "explicit_plain:app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.factory is False

    def test_asgi3_callable_keeps_factory_false(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        """``async def app(scope, receive, send)`` is the app, not a factory.

        Both forms are coroutine functions; the helper distinguishes
        them by arity. The 3-arg ASGI3 callable must NOT trigger
        ``factory=True`` (uvicorn would then call it with no args and
        crash).
        """
        _install_module(
            tmp_path,
            "explicit_asgi3",
            "async def app(scope, receive, send):\n    return None\n",
        )

        code, _out, err = _run(
            ["dev", "--app", "explicit_asgi3:app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.factory is False

    def test_sync_zero_arg_factory_sets_factory_true(
        self,
        tmp_path: Path,
        stub_uvicorn: Any,
    ) -> None:
        """A plain ``def app():`` that returns an ASGI app is also a factory."""
        _install_module(
            tmp_path,
            "explicit_sync_factory",
            "def app() -> object:\n    return object()\n",
        )

        code, _out, err = _run(
            ["dev", "--app", "explicit_sync_factory:app", "--no-reload"],
            cwd=tmp_path,
        )

        assert code == dev_cmd.EXIT_OK, err
        assert stub_uvicorn.instances[0].config.factory is True


class TestFactoryDetectionHelper:
    def test_helper_returns_true_for_async_function(
        self,
        tmp_path: Path,
    ) -> None:
        _install_module(
            tmp_path,
            "helper_async",
            "async def app() -> object:\n    return object()\n",
        )
        import helper_async  # type: ignore[import-not-found]

        # Ensure it is loaded into sys.modules before the helper runs.
        assert helper_async.app  # touch attribute

        assert dev_cmd._is_factory_target(
            module_name="helper_async",
            var_name="app",
        )

    def test_helper_returns_false_for_plain_object(
        self,
        tmp_path: Path,
    ) -> None:
        _install_module(
            tmp_path,
            "helper_plain",
            "app = object()\n",
        )
        import helper_plain  # type: ignore[import-not-found]

        assert helper_plain.app  # touch attribute

        assert not dev_cmd._is_factory_target(
            module_name="helper_plain",
            var_name="app",
        )

    def test_helper_returns_false_when_module_missing(self) -> None:
        """Cache-eviction safety net keeps today's behaviour."""
        assert not dev_cmd._is_factory_target(
            module_name="nonexistent_module_xyz",
            var_name="app",
        )

    def test_helper_returns_false_when_attr_missing(
        self,
        tmp_path: Path,
    ) -> None:
        _install_module(
            tmp_path,
            "helper_missing",
            "other = object()\n",
        )
        import helper_missing  # type: ignore[import-not-found]

        assert helper_missing.other  # touch attribute

        assert not dev_cmd._is_factory_target(
            module_name="helper_missing",
            var_name="app",
        )

    def test_helper_returns_false_for_asgi3_signature(
        self,
        tmp_path: Path,
    ) -> None:
        """``async def app(scope, receive, send)`` has required args -> False."""
        _install_module(
            tmp_path,
            "helper_asgi3",
            "async def app(scope, receive, send):\n    return None\n",
        )
        import helper_asgi3  # type: ignore[import-not-found]

        assert helper_asgi3.app

        assert not dev_cmd._is_factory_target(
            module_name="helper_asgi3",
            var_name="app",
        )

    def test_helper_returns_true_for_factory_with_kwargs_only(
        self,
        tmp_path: Path,
    ) -> None:
        """``async def app(**kw)`` has no required positional args -> True."""
        _install_module(
            tmp_path,
            "helper_kwargs",
            "async def app(**kw) -> object:\n    return object()\n",
        )
        import helper_kwargs  # type: ignore[import-not-found]

        assert helper_kwargs.app

        assert dev_cmd._is_factory_target(
            module_name="helper_kwargs",
            var_name="app",
        )
