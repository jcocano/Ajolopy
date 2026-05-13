"""Acceptance: ``@Injectable`` decorator behaviour.

Covers every checkbox under ``## Acceptance criteria`` in
``specs/injectable.md``: bare form, parameterised form, scope-value
validation, inheritance, re-decoration, public-surface re-exports, and
the integration smoke test against ``@Module`` (AJ-8).
"""

import pytest

from ajolopy import Injectable, Module, compile_module
from ajolopy.di import InjectableConfigError, InjectableError


class TestBareDecorator:
    """``@Injectable`` (no parens) form."""

    def test_bare_stamps_singleton_scope_and_returns_class(self) -> None:
        @Injectable
        class Logger:
            sentinel = "kept"

        # The class is returned unchanged: its own attributes survive.
        assert Logger.sentinel == "kept"
        # The scope stamp is on its own ``__dict__`` (not inherited).
        assert Logger.__dict__["__ajolopy_scope__"] == "singleton"
        assert Logger.__ajolopy_scope__ == "singleton"

    def test_bare_does_not_touch_attributes_or_init(self) -> None:
        @Injectable
        class Service:
            class_attr = 42

            def __init__(self, x: int = 7) -> None:
                self.x = x

            def method(self) -> str:
                return "ok"

        assert Service.class_attr == 42
        instance = Service(x=11)
        assert instance.x == 11
        assert instance.method() == "ok"


class TestParameterisedDecorator:
    """``@Injectable(scope=...)`` form, including empty parens."""

    def test_singleton_scope_stamped(self) -> None:
        @Injectable(scope="singleton")
        class DatabaseService:
            pass

        assert DatabaseService.__ajolopy_scope__ == "singleton"

    def test_request_scope_stamped(self) -> None:
        @Injectable(scope="request")
        class RequestContext:
            pass

        assert RequestContext.__ajolopy_scope__ == "request"

    def test_transient_scope_stamped(self) -> None:
        @Injectable(scope="transient")
        class IdGenerator:
            pass

        assert IdGenerator.__ajolopy_scope__ == "transient"

    def test_empty_parens_defaults_to_singleton(self) -> None:
        @Injectable()
        class Logger:
            pass

        assert Logger.__ajolopy_scope__ == "singleton"


class TestScopeValidation:
    """Decoration-time rejection of illegal scope values."""

    def test_unknown_string_scope_raises(self) -> None:
        with pytest.raises(InjectableConfigError, match="bogus"):

            @Injectable(scope="bogus")  # type: ignore[arg-type]
            class Service:
                pass

    def test_unknown_string_scope_message_lists_legal_scopes(self) -> None:
        with pytest.raises(InjectableConfigError) as info:

            @Injectable(scope="weird")  # type: ignore[arg-type]
            class Service:
                pass

        message = str(info.value)
        assert "singleton" in message
        assert "request" in message
        assert "transient" in message

    def test_none_scope_raises(self) -> None:
        with pytest.raises(InjectableConfigError, match="None"):

            @Injectable(scope=None)  # type: ignore[arg-type]
            class Service:
                pass

    def test_int_scope_raises(self) -> None:
        with pytest.raises(InjectableConfigError, match="123"):

            @Injectable(scope=123)  # type: ignore[arg-type]
            class Service:
                pass

    def test_config_error_is_subclass_of_injectable_error(self) -> None:
        """The whole error tree must be catchable via ``InjectableError``."""
        assert issubclass(InjectableConfigError, InjectableError)


class TestInheritance:
    """``__ajolopy_scope__`` is *not* inherited by subclasses."""

    def test_subclass_does_not_inherit_scope_attribute_in_dict(self) -> None:
        @Injectable(scope="request")
        class Parent:
            pass

        class Child(Parent):  # pyright: ignore[reportUntypedBaseClass]
            pass

        assert "__ajolopy_scope__" in Parent.__dict__
        assert "__ajolopy_scope__" not in Child.__dict__

    def test_subclass_can_be_decorated_independently(self) -> None:
        @Injectable(scope="singleton")
        class Parent:
            pass

        @Injectable(scope="transient")
        class Child(Parent):  # pyright: ignore[reportUntypedBaseClass]
            pass

        assert Parent.__dict__["__ajolopy_scope__"] == "singleton"
        assert Child.__dict__["__ajolopy_scope__"] == "transient"


class TestReDecoration:
    """Decorating the same class twice is an explicit configuration bug."""

    def test_re_decoration_raises_with_class_name(self) -> None:
        @Injectable
        class Foo:
            pass

        with pytest.raises(InjectableConfigError, match="Foo"):
            Injectable(Foo)

    def test_re_decoration_with_parameterised_form_raises(self) -> None:
        @Injectable(scope="request")
        class Bar:
            pass

        with pytest.raises(InjectableConfigError, match="already decorated"):
            Injectable(scope="transient")(Bar)


class TestPublicSurface:
    """Re-exports from both ``ajolopy`` and ``ajolopy.di``."""

    def test_top_level_import(self) -> None:
        from ajolopy import Injectable as TopLevel

        assert TopLevel is Injectable

    def test_di_subpackage_import(self) -> None:
        from ajolopy.di import Injectable as DiLevel

        assert DiLevel is Injectable


# --------------------------------------------------------------------------
# Integration smoke test with ``@Module`` (AJ-8).
# --------------------------------------------------------------------------


class TestModuleIntegration:
    """End-to-end: ``@Injectable`` + ``@Module`` + ``compile_module``."""

    def test_request_scope_propagates_to_compiled_container(self) -> None:
        from ajolopy.di import OutOfScopeError

        @Injectable(scope="request")
        class RequestState:
            pass

        @Module(providers=[RequestState])
        class AppModule:
            pass

        compiled = compile_module(AppModule)
        container = compiled.container

        # Outside any request scope the resolve must fail — proving the
        # registration honoured ``request`` (and not the fallback
        # ``singleton``).
        with pytest.raises(OutOfScopeError):
            container.resolve(RequestState)

        # Inside a request scope, two resolves return the same instance;
        # sequential scopes produce distinct instances. Together these
        # verify the request lifecycle is exercised end-to-end.
        with container.request_scope():
            a = container.resolve(RequestState)
            b = container.resolve(RequestState)
            assert a is b
        with container.request_scope():
            c = container.resolve(RequestState)
            assert c is not a

    def test_bare_injectable_registers_as_singleton(self) -> None:
        @Injectable
        class Logger:
            pass

        @Module(providers=[Logger])
        class AppModule:
            pass

        compiled = compile_module(AppModule)
        # Singleton: two resolves return the same instance, outside any
        # request scope (which would be required for ``request``).
        a = compiled.container.resolve(Logger)
        b = compiled.container.resolve(Logger)
        assert a is b
        assert isinstance(a, Logger)

    def test_undecorated_class_still_registers_as_singleton(self) -> None:
        """The compiler's fallback already handles bare-class providers."""

        class PlainService:
            pass

        @Module(providers=[PlainService])
        class AppModule:
            pass

        compiled = compile_module(AppModule)
        a = compiled.container.resolve(PlainService)
        b = compiled.container.resolve(PlainService)
        assert a is b
        assert isinstance(a, PlainService)

    def test_transient_scope_propagates_to_compiled_container(self) -> None:
        @Injectable(scope="transient")
        class IdGenerator:
            pass

        @Module(providers=[IdGenerator])
        class AppModule:
            pass

        compiled = compile_module(AppModule)
        a = compiled.container.resolve(IdGenerator)
        b = compiled.container.resolve(IdGenerator)
        assert a is not b
