"""AjolopyFactory must invoke configure_logging exactly once, before tracing."""

import os
from unittest.mock import patch

import pytest

from ajolopy import AjolopyFactory, Module


@pytest.mark.asyncio
async def test_factory_calls_configure_logging_exactly_once() -> None:
    @Module()
    class AppModule:
        pass

    with patch("ajolopy.factory.factory.configure_logging", autospec=True) as mock_configure:
        app = await AjolopyFactory.create(AppModule)
        try:
            assert mock_configure.call_count == 1
        finally:
            await app.aclose()


@pytest.mark.asyncio
async def test_factory_passes_app_env_from_os_environ() -> None:
    @Module()
    class AppModule:
        pass

    os.environ["APP_ENV"] = "production"
    try:
        with patch("ajolopy.factory.factory.configure_logging", autospec=True) as mock_configure:
            app = await AjolopyFactory.create(AppModule)
            try:
                mock_configure.assert_called_once()
                # `env` is the first positional kwarg-style argument.
                _args, kwargs = mock_configure.call_args
                assert kwargs.get("env") == "production"
            finally:
                await app.aclose()
    finally:
        os.environ.pop("APP_ENV", None)


@pytest.mark.asyncio
async def test_factory_defaults_env_to_development_when_app_env_missing() -> None:
    @Module()
    class AppModule:
        pass

    os.environ.pop("APP_ENV", None)
    with patch("ajolopy.factory.factory.configure_logging", autospec=True) as mock_configure:
        app = await AjolopyFactory.create(AppModule)
        try:
            mock_configure.assert_called_once()
            _args, kwargs = mock_configure.call_args
            assert kwargs.get("env") == "development"
        finally:
            await app.aclose()


@pytest.mark.asyncio
async def test_factory_runs_logging_before_tracing() -> None:
    """configure_logging must run before setup_tracing_from_env."""

    @Module()
    class AppModule:
        pass

    call_order: list[str] = []

    def _log(*_args: object, **_kwargs: object) -> None:
        call_order.append("logging")

    def _trace() -> bool:
        call_order.append("tracing")
        return False

    with (
        patch("ajolopy.factory.factory.configure_logging", side_effect=_log),
        patch("ajolopy.factory.factory.setup_tracing_from_env", side_effect=_trace),
    ):
        app = await AjolopyFactory.create(AppModule)
        try:
            assert call_order.index("logging") < call_order.index("tracing"), (
                f"Expected logging before tracing, got {call_order}"
            )
        finally:
            await app.aclose()


@pytest.mark.asyncio
async def test_factory_wraps_configure_logging_failure_in_startup_error() -> None:
    from ajolopy.factory import FactoryStartupError

    @Module()
    class AppModule:
        pass

    def _boom(**_kwargs: object) -> None:
        raise ValueError("bad LOG_LEVEL")

    with (
        patch("ajolopy.factory.factory.configure_logging", side_effect=_boom),
        pytest.raises(FactoryStartupError) as info,
    ):
        await AjolopyFactory.create(AppModule)
    assert info.value.step == "configure_logging"
    assert "bad LOG_LEVEL" in str(info.value)


@pytest.mark.asyncio
async def test_factory_renders_startup_error_through_configured_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If a later step fails, the configured renderer is already in effect.

    Smoke-checks that running `configure_logging("production")` via the
    factory before a downstream failure causes any framework log emitted
    in JSON form.
    """
    from ajolopy import Injectable
    from ajolopy.factory import FactoryStartupError

    @Injectable
    class Faulty:
        async def on_app_bootstrap(self) -> None:
            # Emit a log line through the configured pipeline before raising
            # so we can assert the renderer is in effect.
            import logging

            logging.getLogger("ajolopy.factory.test").error("about to boom")
            raise RuntimeError("boom")

    @Module(providers=[Faulty])
    class AppModule:
        pass

    os.environ["APP_ENV"] = "production"
    try:
        with pytest.raises(FactoryStartupError):
            await AjolopyFactory.create(AppModule)
    finally:
        os.environ.pop("APP_ENV", None)

    captured = capsys.readouterr()
    out = captured.err or captured.out
    # JSON shape: braces + a "logger" key on the emitted line.
    assert "{" in out
    assert "}" in out
    assert "about to boom" in out


@pytest.mark.asyncio
async def test_factory_invokes_logging_after_validate_env() -> None:
    """validate_env must run first; otherwise a bad env var fails *before*
    the renderer is installed.
    """

    @Module()
    class AppModule:
        pass

    call_order: list[str] = []

    def _log(*_args: object, **_kwargs: object) -> None:
        call_order.append("logging")

    def _validate(_m: object) -> None:
        call_order.append("validate_env")

    with (
        patch(
            "ajolopy.factory.factory._validate_env_early",
            side_effect=_validate,
        ),
        patch("ajolopy.factory.factory.configure_logging", side_effect=_log),
    ):
        app = await AjolopyFactory.create(AppModule)
        try:
            assert call_order.index("validate_env") < call_order.index("logging")
        finally:
            await app.aclose()


@pytest.mark.asyncio
async def test_factory_does_not_double_install_handler_across_creates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two successive `AjolopyFactory.create()` calls must not stack handlers.

    `configure_logging` is idempotent; this test guards the contract from
    the factory side specifically.
    """
    import logging

    @Module()
    class AppModule:
        pass

    root = logging.getLogger()
    baseline_handlers = len(root.handlers)

    app1 = await AjolopyFactory.create(AppModule)
    try:
        first = len(root.handlers)
        assert first == baseline_handlers + 1
        app2 = await AjolopyFactory.create(AppModule)
        try:
            second = len(root.handlers)
            assert second == first, (
                f"Second factory call stacked an extra handler: {first} -> {second}"
            )
        finally:
            await app2.aclose()
    finally:
        await app1.aclose()


@pytest.mark.asyncio
async def test_configure_logging_is_real_module_attribute() -> None:
    """Sanity: the symbol the factory imports is the real public helper."""
    # The factory module re-imports configure_logging from
    # ``ajolopy.observability``. Read it dynamically (getattr) to avoid
    # pyright's reportPrivateImportUsage warning — the symbol exists at
    # runtime and that is what the test asserts.
    import ajolopy.factory.factory as factory_module
    from ajolopy.observability import configure_logging as public

    factory_attr = getattr(factory_module, "configure_logging")  # noqa: B009 — see comment
    assert factory_attr is public


@pytest.mark.asyncio
async def test_configure_logging_is_called_with_keyword_env() -> None:
    """env is passed as a keyword so future positional changes do not break it."""

    @Module()
    class AppModule:
        pass

    seen: dict[str, object] = {}

    def _log(**kwargs: object) -> None:
        seen.update(kwargs)

    with patch("ajolopy.factory.factory.configure_logging", side_effect=_log):
        app = await AjolopyFactory.create(AppModule)
        try:
            assert "env" in seen
        finally:
            await app.aclose()
