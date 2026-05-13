"""Registration-time behaviour for ``Container.register``."""

import pytest

from ajolopy.di import Container, ContainerConfigError


class _Service:
    pass


class _OtherService:
    pass


class TestDefaultScope:
    def test_default_scope_is_singleton(self) -> None:
        container = Container()
        container.register(_Service)
        a = container.resolve(_Service)
        b = container.resolve(_Service)
        assert a is b

    def test_explicit_transient(self) -> None:
        container = Container()
        container.register(_Service, scope="transient")
        a = container.resolve(_Service)
        b = container.resolve(_Service)
        assert a is not b

    def test_unknown_scope_raises(self) -> None:
        container = Container()
        with pytest.raises(ContainerConfigError, match="Unknown scope"):
            container.register(_Service, scope="weird")  # type: ignore[arg-type]


class TestInstanceProvider:
    def test_instance_bypasses_init(self) -> None:
        sentinel = _Service()
        container = Container()
        container.register(_Service, instance=sentinel)
        assert container.resolve(_Service) is sentinel

    def test_instance_with_transient_scope_raises(self) -> None:
        container = Container()
        with pytest.raises(ContainerConfigError, match="implies singleton scope"):
            container.register(_Service, instance=_Service(), scope="transient")

    def test_instance_with_request_scope_raises(self) -> None:
        container = Container()
        with pytest.raises(ContainerConfigError, match="implies singleton scope"):
            container.register(_Service, instance=_Service(), scope="request")


class TestFactoryProvider:
    def test_factory_called_lazily(self) -> None:
        calls: list[int] = []

        def factory(_: Container) -> _Service:
            calls.append(1)
            return _Service()

        container = Container()
        container.register(_Service, factory=factory)
        assert calls == []
        container.resolve(_Service)
        assert calls == [1]

    def test_factory_receives_container(self) -> None:
        received: list[Container] = []
        container = Container()

        def factory(c: Container) -> _Service:
            received.append(c)
            return _Service()

        container.register(_Service, factory=factory)
        container.resolve(_Service)
        assert received == [container]

    def test_instance_and_factory_are_mutually_exclusive(self) -> None:
        container = Container()
        with pytest.raises(ContainerConfigError, match="mutually exclusive"):
            container.register(
                _Service,
                instance=_Service(),
                factory=lambda _c: _Service(),
            )


class TestReRegistration:
    def test_re_register_without_overwrite_raises(self) -> None:
        container = Container()
        container.register(_Service)
        with pytest.raises(ContainerConfigError, match="already registered"):
            container.register(_Service)

    def test_overwrite_replaces_registration(self) -> None:
        first = _Service()
        second = _Service()
        container = Container()
        container.register(_Service, instance=first)
        container.register(_Service, instance=second, overwrite=True)
        assert container.resolve(_Service) is second


class TestMembership:
    def test_is_registered_and_contains(self) -> None:
        container = Container()
        assert not container.is_registered(_Service)
        assert _Service not in container
        container.register(_Service)
        assert container.is_registered(_Service)
        assert _Service in container
        assert _OtherService not in container

    def test_contains_with_non_type_returns_false(self) -> None:
        container = Container()
        assert "not a type" not in container
