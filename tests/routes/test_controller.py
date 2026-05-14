"""Decoration-time semantics for ``@Controller(prefix)``.

These tests cover the unit-level behaviour of the decorator: metadata
stamping, prefix normalisation, validation errors, no-inheritance, and
re-decoration rejection. End-to-end registration through
``mount_routes`` lives in ``tests/routes/test_controller_integration.py``.
"""

import pytest

from ajolopy.routes import (
    Controller,
    ControllerConfigError,
    ControllerError,
    get_controller_prefix,
)
from ajolopy.routes.controller import CONTROLLER_PREFIX_ATTR


class TestStampMetadata:
    def test_returns_class_unchanged(self) -> None:
        @Controller("/users")
        class UsersController:
            value: int = 7

        assert UsersController.value == 7
        # The decorator must not wrap or subclass — same class object in,
        # same class object out.
        assert UsersController.__name__ == "UsersController"
        assert UsersController.__qualname__.endswith("UsersController")

    def test_stamps_prefix_attribute(self) -> None:
        @Controller("/users")
        class UsersController:
            pass

        assert UsersController.__dict__[CONTROLLER_PREFIX_ATTR] == "/users"
        assert getattr(UsersController, CONTROLLER_PREFIX_ATTR) == "/users"

    def test_get_controller_prefix_returns_stamped_value(self) -> None:
        @Controller("/users")
        class UsersController:
            pass

        assert get_controller_prefix(UsersController) == "/users"

    def test_get_controller_prefix_returns_none_for_undecorated(self) -> None:
        class Plain:
            pass

        assert get_controller_prefix(Plain) is None

    def test_get_controller_prefix_returns_none_for_non_class(self) -> None:
        # Passing an instance rather than a class is a soft contract;
        # the helper returns ``None`` instead of raising.
        assert get_controller_prefix(object()) is None  # pyright: ignore[reportArgumentType]


class TestPrefixNormalisation:
    def test_trailing_slash_is_stripped(self) -> None:
        @Controller("/users/")
        class UsersController:
            pass

        assert UsersController.__dict__[CONTROLLER_PREFIX_ATTR] == "/users"

    def test_multiple_trailing_slashes_are_stripped(self) -> None:
        @Controller("/users///")
        class UsersController:
            pass

        assert UsersController.__dict__[CONTROLLER_PREFIX_ATTR] == "/users"

    def test_no_trailing_slash_preserves_value(self) -> None:
        @Controller("/users")
        class UsersController:
            pass

        assert UsersController.__dict__[CONTROLLER_PREFIX_ATTR] == "/users"

    def test_empty_string_is_legal_and_stamps_empty(self) -> None:
        @Controller("")
        class Root:
            pass

        assert Root.__dict__[CONTROLLER_PREFIX_ATTR] == ""

    def test_leading_slash_is_preserved(self) -> None:
        @Controller("/")
        class Slash:
            pass

        # A bare "/" rstrips to the empty string — this prevents the
        # silent collision where ``/`` + ``/users`` becomes ``//users``.
        assert Slash.__dict__[CONTROLLER_PREFIX_ATTR] == ""

    def test_nested_prefix_preserved_except_trailing_slash(self) -> None:
        @Controller("/api/v1/users/")
        class UsersController:
            pass

        assert UsersController.__dict__[CONTROLLER_PREFIX_ATTR] == "/api/v1/users"


class TestPrefixValidation:
    def test_integer_prefix_raises(self) -> None:
        with pytest.raises(ControllerConfigError, match="must be a str"):
            Controller(42)  # pyright: ignore[reportArgumentType]

    def test_integer_prefix_message_names_offending_value_and_type(self) -> None:
        with pytest.raises(ControllerConfigError) as exc_info:
            Controller(42)  # pyright: ignore[reportArgumentType]
        message = str(exc_info.value)
        assert "42" in message
        assert "int" in message

    def test_none_prefix_raises(self) -> None:
        with pytest.raises(ControllerConfigError, match="must be a str"):
            Controller(None)  # pyright: ignore[reportArgumentType]

    def test_none_prefix_message_names_offending_value_and_type(self) -> None:
        with pytest.raises(ControllerConfigError) as exc_info:
            Controller(None)  # pyright: ignore[reportArgumentType]
        message = str(exc_info.value)
        assert "None" in message
        assert "NoneType" in message

    def test_bytes_prefix_raises(self) -> None:
        with pytest.raises(ControllerConfigError, match="must be a str"):
            Controller(b"/users")  # pyright: ignore[reportArgumentType]

    def test_list_prefix_raises(self) -> None:
        with pytest.raises(ControllerConfigError, match="must be a str"):
            Controller(["/users"])  # pyright: ignore[reportArgumentType]

    def test_validation_error_subclasses_controller_error(self) -> None:
        # ``ControllerConfigError`` extends ``ControllerError`` so users
        # can catch the controller surface with one type.
        with pytest.raises(ControllerError):
            Controller(42)  # pyright: ignore[reportArgumentType]

    def test_controller_error_subclasses_runtime_error(self) -> None:
        # Mirrors ``RouteLayerError`` — both layers sit under
        # ``RuntimeError`` so a blanket ``except RuntimeError`` still
        # catches framework misconfiguration.
        assert issubclass(ControllerError, RuntimeError)
        assert issubclass(ControllerConfigError, ControllerError)


class TestReDecoration:
    def test_reapplying_controller_raises(self) -> None:
        @Controller("/users")
        class UsersController:
            pass

        with pytest.raises(ControllerConfigError, match="re-applied"):
            Controller("/different")(UsersController)

    def test_reapplying_controller_message_names_class_and_existing_prefix(self) -> None:
        @Controller("/users")
        class UsersController:
            pass

        with pytest.raises(ControllerConfigError) as exc_info:
            Controller("/different")(UsersController)
        message = str(exc_info.value)
        assert "UsersController" in message
        assert "/users" in message

    def test_reapplying_same_prefix_still_raises(self) -> None:
        # Re-decoration is rejected regardless of whether the new prefix
        # equals the existing one — the decorator's job is to stamp
        # exactly once.
        @Controller("/users")
        class UsersController:
            pass

        with pytest.raises(ControllerConfigError, match="re-applied"):
            Controller("/users")(UsersController)


class TestInheritance:
    def test_subclass_does_not_inherit_prefix_in_dict(self) -> None:
        @Controller("/users")
        class Parent:
            pass

        class Child(Parent):
            pass

        # The attribute lives on Parent's __dict__ only.
        assert CONTROLLER_PREFIX_ATTR in Parent.__dict__
        assert CONTROLLER_PREFIX_ATTR not in Child.__dict__

    def test_subclass_can_be_decorated_independently(self) -> None:
        @Controller("/users")
        class Parent:
            pass

        @Controller("/admin")
        class Child(Parent):
            pass

        # Each class carries its own prefix on its own __dict__.
        assert Parent.__dict__[CONTROLLER_PREFIX_ATTR] == "/users"
        assert Child.__dict__[CONTROLLER_PREFIX_ATTR] == "/admin"

    def test_get_controller_prefix_does_not_walk_mro(self) -> None:
        @Controller("/users")
        class Parent:
            pass

        class Child(Parent):
            pass

        # ``getattr(Child, ...)`` *would* walk the MRO and resolve to
        # ``"/users"``; ``get_controller_prefix`` reads __dict__ so it
        # returns ``None`` for the undecorated child.
        assert get_controller_prefix(Parent) == "/users"
        assert get_controller_prefix(Child) is None


class TestPublicSurface:
    def test_top_level_import_resolves(self) -> None:
        from ajolopy import Controller as TopLevelController

        assert TopLevelController is Controller

    def test_routes_subpackage_import_resolves(self) -> None:
        from ajolopy.routes import Controller as RoutesController

        assert RoutesController is Controller

    def test_errors_exported_from_routes(self) -> None:
        from ajolopy.routes import ControllerConfigError as ExportedConfigError
        from ajolopy.routes import ControllerError as ExportedError

        assert ExportedConfigError is ControllerConfigError
        assert ExportedError is ControllerError


class TestApiShape:
    def test_decorator_is_callable_returning_callable(self) -> None:
        # ``Controller("/users")`` returns a decorator; the decorator
        # accepts a class and returns it.
        decorator = Controller("/users")
        assert callable(decorator)

        class Cls:
            pass

        result = decorator(Cls)
        assert result is Cls

    @pytest.mark.parametrize(
        "prefix",
        [
            "/users",
            "/api/v1/users",
            "/users-and-admins",
            "/x.y.z",
            "/segment_with_underscore",
        ],
    )
    def test_accepts_a_variety_of_legal_prefixes(self, prefix: str) -> None:
        @Controller(prefix)
        class Decorated:
            pass

        assert Decorated.__dict__[CONTROLLER_PREFIX_ATTR] == prefix.rstrip("/")

    def test_decorator_does_not_swallow_class_attributes(self) -> None:
        @Controller("/users")
        class WithAttrs:
            answer: int = 42

            def method(self) -> int:
                return self.answer

        instance = WithAttrs()
        assert instance.answer == 42
        assert instance.method() == 42
