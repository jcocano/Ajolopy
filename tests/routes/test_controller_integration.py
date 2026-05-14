"""Integration of ``@Controller`` with ``mount_routes`` and ``@Module``.

These tests cover the prefix-concatenation rules at registration time
plus the end-to-end flow through Starlette's ``TestClient`` and the
``@Module`` / ``compile_module`` machinery.
"""

from typing import Annotated, Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from ajolopy import Controller, Module, compile_module
from ajolopy.di import Injectable
from ajolopy.http import Body, Param, create_app
from ajolopy.routes import Get, Post, RouteConfigError, mount_routes


class TestPrefixConcatenation:
    """Each of the four join rules listed in the spec, one test apiece."""

    def test_prefix_users_plus_slash_mounts_users_slash(self) -> None:
        @Controller("/users")
        class UsersController:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

        app = create_app()
        mount_routes(app, [UsersController])
        assert _route_exists(app, "/users/", "GET")

    def test_prefix_users_plus_path_param_mounts_users_path_param(self) -> None:
        @Controller("/users")
        class UsersController:
            @Get("/{user_id}")
            async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
                return {"id": user_id}

        app = create_app()
        mount_routes(app, [UsersController])
        assert _route_exists(app, "/users/{user_id}", "GET")

    def test_prefix_users_plus_empty_path_mounts_users(self) -> None:
        @Controller("/users")
        class UsersController:
            @Get("")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

        app = create_app()
        mount_routes(app, [UsersController])
        assert _route_exists(app, "/users", "GET")

    def test_empty_prefix_plus_path_mounts_path_verbatim(self) -> None:
        @Controller("")
        class Root:
            @Get("/foo")
            async def foo(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        mount_routes(app, [Root])
        assert _route_exists(app, "/foo", "GET")

    def test_normalised_trailing_slash_does_not_double_up(self) -> None:
        # ``"/users/"`` normalises to ``"/users"`` at decoration time;
        # ``"/{id}"`` then concatenates without producing ``//{id}``.
        @Controller("/users/")
        class UsersController:
            @Get("/{user_id}")
            async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
                return {"id": user_id}

        app = create_app()
        mount_routes(app, [UsersController])
        assert _route_exists(app, "/users/{user_id}", "GET")
        assert not _route_exists(app, "//{user_id}", "GET")


class TestBackwardsCompatibility:
    def test_class_without_controller_keeps_aj16_behaviour(self) -> None:
        # A bare class with method decorators (no ``@Controller``)
        # registers each method-level path verbatim.
        class Plain:
            @Get("/health")
            async def health(self) -> dict[str, str]:
                return {"status": "ok"}

            @Post("/widgets")
            async def create_widget(self) -> dict[str, str]:
                return {"id": "w_1"}

        app = create_app()
        mount_routes(app, [Plain])
        assert _route_exists(app, "/health", "GET")
        assert _route_exists(app, "/widgets", "POST")
        # The prefix attribute should be absent on the bare class.
        assert "__ajolopy_route_prefix__" not in Plain.__dict__

    def test_mixed_controller_and_plain_classes_coexist(self) -> None:
        @Controller("/users")
        class Users:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

        class Plain:
            @Get("/health")
            async def health(self) -> dict[str, str]:
                return {"status": "ok"}

        app = create_app()
        mount_routes(app, [Users, Plain])
        assert _route_exists(app, "/users/", "GET")
        assert _route_exists(app, "/health", "GET")


class TestForwardingToAddRoute:
    def test_full_paths_forwarded_to_add_route(self) -> None:
        @Controller("/users")
        class UsersController:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

            @Get("/{user_id}")
            async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
                return {"id": user_id}

        app = create_app()
        with patch("ajolopy.routes.mount.add_route") as add_route_mock:
            mount_routes(app, [UsersController])

        assert add_route_mock.call_count == 2
        method_path_pairs = {(call.args[1], call.args[2]) for call in add_route_mock.call_args_list}
        assert method_path_pairs == {("GET", "/users/"), ("GET", "/users/{user_id}")}


class TestDuplicateDetectionUsesFullPath:
    def test_two_controllers_same_full_path_raises(self) -> None:
        @Controller("/users")
        class A:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

        @Controller("/users")
        class B:
            @Get("/")
            async def list_users_again(self) -> dict[str, object]:
                return {"items": []}

        app = create_app()
        with pytest.raises(RouteConfigError, match="Duplicate"):
            mount_routes(app, [A, B])

    def test_same_method_path_resolves_to_distinct_full_paths(self) -> None:
        # Both classes declare ``@Get("/")`` but distinct prefixes ->
        # no collision because the *full* path is what mount_routes
        # de-duplicates against.
        @Controller("/users")
        class Users:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

        @Controller("/admins")
        class Admins:
            @Get("/")
            async def list_admins(self) -> dict[str, object]:
                return {"items": []}

        app = create_app()
        mount_routes(app, [Users, Admins])
        assert _route_exists(app, "/users/", "GET")
        assert _route_exists(app, "/admins/", "GET")


class TestEndToEndViaTestClient:
    def test_get_with_prefix(self) -> None:
        @Controller("/users")
        class UsersController:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

            @Get("/{user_id}")
            async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
                return {"id": user_id}

        app = create_app()
        mount_routes(app, [UsersController])
        with TestClient(app) as client:
            list_response = client.get("/users/")
            get_response = client.get("/users/u_42")

        assert list_response.status_code == 200
        assert list_response.json() == {"items": []}
        assert get_response.status_code == 200
        assert get_response.json() == {"id": "u_42"}

    def test_post_with_prefix_and_body(self) -> None:
        class CreateUserDto(BaseModel):
            email: str
            name: str

        @Controller("/users")
        class UsersController:
            @Post("/")
            async def create_user(self, body: Annotated[CreateUserDto, Body()]) -> dict[str, str]:
                return {"id": "u_1", "email": body.email, "name": body.name}

        app = create_app()
        mount_routes(app, [UsersController])
        with TestClient(app) as client:
            response = client.post("/users/", json={"email": "a@b.c", "name": "Alice"})

        assert response.status_code == 200
        assert response.json() == {"id": "u_1", "email": "a@b.c", "name": "Alice"}


class TestModuleIntegration:
    def test_controller_in_module_is_mounted_via_compile_module(self) -> None:
        @Controller("/users")
        class UsersController:
            @Get("/")
            async def list_users(self) -> dict[str, object]:
                return {"items": []}

        @Module(controllers=[UsersController])
        class AppModule:
            pass

        compiled = compile_module(AppModule)
        assert UsersController in compiled.controllers
        # The module compiler registered the controller as a provider
        # so the container can resolve it. Singletons share state, so
        # ``resolve`` returns the same instance on each call.
        instance = compiled.container.resolve(UsersController)
        assert isinstance(instance, UsersController)

        app = create_app()
        mount_routes(app, [compiled.container.resolve(c) for c in compiled.controllers])
        with TestClient(app) as client:
            response = client.get("/users/")
        assert response.status_code == 200
        assert response.json() == {"items": []}

    def test_controller_with_di_dependency_is_resolved(self) -> None:
        """Spec: a controller whose ``__init__`` takes a DI dependency
        is built with the dep injected when the route handler runs."""

        @Injectable
        class Db:
            def __init__(self) -> None:
                self.name = "in-memory"

        @Controller("/items")
        class ItemsController:
            def __init__(self, db: Db) -> None:
                self.db = db

            @Get("/")
            async def list_items(self) -> dict[str, str]:
                return {"backend": self.db.name}

        @Module(providers=[Db], controllers=[ItemsController])
        class AppModule:
            pass

        compiled = compile_module(AppModule)

        app = create_app()
        controllers = [compiled.container.resolve(c) for c in compiled.controllers]
        mount_routes(app, controllers)

        with TestClient(app) as client:
            response = client.get("/items/")

        assert response.status_code == 200
        assert response.json() == {"backend": "in-memory"}

    def test_module_compile_preserves_controller_registration_order(self) -> None:
        @Controller("/a")
        class A:
            @Get("/")
            async def a(self) -> dict[str, str]:
                return {"x": "a"}

        @Controller("/b")
        class B:
            @Get("/")
            async def b(self) -> dict[str, str]:
                return {"x": "b"}

        @Module(controllers=[A, B])
        class AppModule:
            pass

        compiled = compile_module(AppModule)
        assert compiled.controllers == (A, B)


def _route_exists(app: Any, path: str, method: str) -> bool:
    starlette_app: Starlette = app
    for route in starlette_app.router.routes:
        path_attr = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path_attr == path and methods is not None and method in methods:
            return True
    return False
