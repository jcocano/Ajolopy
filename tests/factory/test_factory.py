"""Acceptance: ``AjolopyFactory.create`` happy path + bootstrap pipeline."""

import os

import pytest

from ajolopy import (
    AjolopyApp,
    AjolopyFactory,
    Get,
    Injectable,
    Module,
    compile_module,
)
from ajolopy.config import BaseConfig
from ajolopy.di import Container
from ajolopy.factory import FactoryConfigError, FactoryStartupError


class _NotAModule:
    pass


@pytest.mark.asyncio
async def test_returns_ajolopy_app() -> None:
    @Module()
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        assert isinstance(app, AjolopyApp)
        assert app.compiled_module is not None
        assert isinstance(app.container, Container)
        assert app.http is not None
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_resolves_every_provider_in_graph() -> None:
    @Injectable
    class Logger:
        pass

    @Injectable
    class Repo:
        def __init__(self, logger: Logger) -> None:
            self.logger = logger

    @Module(providers=[Logger, Repo])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        assert isinstance(app.container.resolve(Logger), Logger)
        assert isinstance(app.container.resolve(Repo), Repo)
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_non_module_root_raises_factory_config_error() -> None:
    with pytest.raises(FactoryConfigError, match="_NotAModule"):
        await AjolopyFactory.create(_NotAModule)


@pytest.mark.asyncio
async def test_compile_module_failure_wraps_in_startup_error() -> None:
    @Module(providers=[int])
    class A:
        pass

    @Module(imports=[A], providers=[int])
    class Root:
        pass

    with pytest.raises(FactoryStartupError) as info:
        await AjolopyFactory.create(Root)
    assert info.value.step == "compile_module"
    assert "Duplicate" in str(info.value) or "duplicate" in str(info.value).lower()


@pytest.mark.asyncio
async def test_env_validation_failure_wraps_in_startup_error() -> None:
    class _Cfg(BaseConfig):
        test_factory_required_var: str  # required, no default

    @Module(providers=[_Cfg])
    class AppModule:
        pass

    # Make sure the env var is not set.
    os.environ.pop("test_factory_required_var", None)
    with pytest.raises(FactoryStartupError) as info:
        await AjolopyFactory.create(AppModule)
    assert info.value.step == "validate_env"
    assert "_Cfg" in str(info.value)


@pytest.mark.asyncio
async def test_env_validation_runs_before_compile_module() -> None:
    """If env validation would fail, compile_module never runs.

    Verified by constructing a graph that *would* fail compile_module
    (duplicate provider) but also has a missing-env BaseConfig. The
    factory should raise the validate_env error, not the compile one.
    """

    class _Cfg2(BaseConfig):
        test_factory_required_var_2: str

    @Module(providers=[_Cfg2, int])
    class A:
        pass

    @Module(imports=[A], providers=[int])  # would trip compile_module
    class Root:
        pass

    os.environ.pop("test_factory_required_var_2", None)
    with pytest.raises(FactoryStartupError) as info:
        await AjolopyFactory.create(Root)
    assert info.value.step == "validate_env"


@pytest.mark.asyncio
async def test_on_app_bootstrap_runs_during_create() -> None:
    seen: list[str] = []

    @Injectable
    class Service:
        async def on_app_bootstrap(self) -> None:
            seen.append("bootstrap")

    @Module(providers=[Service])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        # on_app_bootstrap fired during create().
        assert seen == ["bootstrap"]
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_on_app_bootstrap_failure_wraps_in_startup_error() -> None:
    @Injectable
    class Faulty:
        async def on_app_bootstrap(self) -> None:
            raise RuntimeError("boom")

    @Module(providers=[Faulty])
    class AppModule:
        pass

    with pytest.raises(FactoryStartupError) as info:
        await AjolopyFactory.create(AppModule)
    assert info.value.step == "fire_on_app_bootstrap"
    assert "boom" in str(info.value)


@pytest.mark.asyncio
async def test_compile_module_via_compile_module_function_matches() -> None:
    """The container the factory produces is the same kind compile_module yields."""

    @Injectable
    class Svc:
        pass

    @Module(providers=[Svc])
    class AppModule:
        pass

    factory_app = await AjolopyFactory.create(AppModule)
    try:
        direct = compile_module(AppModule)
        # Both contain a Svc registration; resolves should produce the
        # same type (different singletons because different containers).
        assert isinstance(factory_app.container.resolve(Svc), Svc)
        assert isinstance(direct.container.resolve(Svc), Svc)
    finally:
        await factory_app.aclose()


@pytest.mark.asyncio
async def test_routes_mounted_end_to_end() -> None:
    """End-to-end: a controller's method-decorated routes are reachable.

    Uses bare method decorators (no class-level prefix from AJ-10's
    ``@Controller`` since that lives on a parallel PR). When AJ-10
    merges, AJ-14 inherits the prefix concatenation transparently
    because ``mount_routes`` does the join.
    """
    from starlette.testclient import TestClient

    class UsersController:
        @Get("/users")
        async def list_users(self) -> dict[str, list[str]]:
            return {"items": []}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        client = TestClient(app.http)
        response = client.get("/users")
        assert response.status_code == 200
        assert response.json() == {"items": []}
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_pre_built_container_kwarg() -> None:
    @Injectable
    class Svc:
        pass

    @Module(providers=[Svc])
    class AppModule:
        pass

    custom = Container()
    app = await AjolopyFactory.create(AppModule, container=custom)
    try:
        assert app.container is custom
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_pre_built_http_kwarg() -> None:
    from ajolopy.http import create_app

    @Module()
    class AppModule:
        pass

    custom_http = create_app()
    app = await AjolopyFactory.create(AppModule, http=custom_http)
    try:
        assert app.http is custom_http
    finally:
        await app.aclose()
