"""``mount_routes`` registration semantics."""

from typing import Annotated
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from starlette.applications import Starlette

from ajolopy.http import Body, create_app
from ajolopy.routes import Get, Post, RouteConfigError, mount_routes


class _CreateUserDto(BaseModel):
    email: str
    name: str


class _Users:
    @Get("/users")
    async def list_users(self) -> dict[str, object]:
        return {"items": []}

    @Post("/users")
    async def create_user(self, body: Annotated[_CreateUserDto, Body()]) -> dict[str, str]:
        return {"id": "u_1", "email": body.email}


class _Admin:
    @Get("/admin")
    async def admin(self) -> dict[str, str]:
        return {"role": "admin"}


class TestMountRoutes:
    def test_mounts_methods_for_class(self) -> None:
        app = create_app()
        mount_routes(app, [_Users])
        assert _route_exists(app, "/users", "GET")
        assert _route_exists(app, "/users", "POST")

    def test_mounts_methods_for_pre_built_instance(self) -> None:
        app = create_app()
        mount_routes(app, [_Users()])
        assert _route_exists(app, "/users", "GET")
        assert _route_exists(app, "/users", "POST")

    def test_instance_supplied_is_not_reinstantiated(self) -> None:
        instance = _Users()
        app = create_app()
        with patch.object(_Users, "__init__", return_value=None) as init_spy:
            mount_routes(app, [instance])
            init_spy.assert_not_called()

    def test_forwards_to_add_route(self) -> None:
        app = create_app()
        with patch("ajolopy.routes.mount.add_route") as add_route_mock:
            mount_routes(app, [_Users])
        # Two calls — one per decorated method.
        assert add_route_mock.call_count == 2
        method_path_pairs = {(call.args[1], call.args[2]) for call in add_route_mock.call_args_list}
        assert method_path_pairs == {("GET", "/users"), ("POST", "/users")}
        # Every call should pass the app and a bound method as positional args.
        for call in add_route_mock.call_args_list:
            assert call.args[0] is app
            handler = call.args[3]
            # Bound methods expose ``__self__``; an unbound function does not.
            assert getattr(handler, "__self__", None) is not None

    def test_class_with_no_route_methods_raises(self) -> None:
        class Empty:
            pass

        app = create_app()
        with pytest.raises(RouteConfigError, match="no @Get/@Post"):
            mount_routes(app, [Empty])

    def test_class_with_required_constructor_args_raises(self) -> None:
        class Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Get("/needs")
            async def handler(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        with pytest.raises(RouteConfigError, match="requires constructor argument"):
            mount_routes(app, [Needs])

    def test_constructor_error_points_to_aj14(self) -> None:
        class Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Get("/needs")
            async def handler(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        with pytest.raises(RouteConfigError, match="AJ-14"):
            mount_routes(app, [Needs])

    def test_pre_built_instance_bypasses_constructor_check(self) -> None:
        class Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Get("/needs")
            async def handler(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        mount_routes(app, [Needs(db=object())])
        assert _route_exists(app, "/needs", "GET")

    def test_duplicate_method_path_across_items_raises(self) -> None:
        class Other:
            @Get("/users")
            async def list_users_again(self) -> dict[str, str]:
                return {"items": "again"}

        app = create_app()
        with pytest.raises(RouteConfigError, match="Duplicate"):
            mount_routes(app, [_Users, Other])

    def test_duplicate_error_lists_both_qualnames(self) -> None:
        class Other:
            @Get("/users")
            async def list_users_again(self) -> dict[str, str]:
                return {"items": "again"}

        app = create_app()
        with pytest.raises(RouteConfigError) as exc_info:
            mount_routes(app, [_Users, Other])
        message = str(exc_info.value)
        assert "_Users.list_users" in message
        assert "list_users_again" in message

    def test_two_routes_on_one_class_both_registered(self) -> None:
        class Mixed:
            @Get("/a")
            async def get_a(self) -> dict[str, str]:
                return {"x": "a"}

            @Post("/b")
            async def post_b(self) -> dict[str, str]:
                return {"x": "b"}

        app = create_app()
        mount_routes(app, [Mixed])
        assert _route_exists(app, "/a", "GET")
        assert _route_exists(app, "/b", "POST")

    def test_mounts_multiple_items(self) -> None:
        app = create_app()
        mount_routes(app, [_Users, _Admin])
        assert _route_exists(app, "/users", "GET")
        assert _route_exists(app, "/admin", "GET")


def _route_exists(app: Starlette, path: str, method: str) -> bool:
    for route in app.router.routes:
        path_attr = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path_attr == path and methods is not None and method in methods:
            return True
    return False
