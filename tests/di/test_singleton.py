"""Singleton-scope semantics + ``iter_singletons`` ordering."""

from ajolopy.di import Container


class _Db:
    pass


class _Cache:
    pass


class _Logger:
    pass


class _Repo:
    def __init__(self, db: _Db) -> None:
        self.db = db


class _Service:
    def __init__(self, repo: _Repo, cache: _Cache) -> None:
        self.repo = repo
        self.cache = cache


def test_same_instance_across_resolves() -> None:
    container = Container()
    container.register(_Db)
    a = container.resolve(_Db)
    b = container.resolve(_Db)
    assert a is b


def test_recursive_init_dependency_resolution() -> None:
    container = Container()
    container.register(_Db)
    container.register(_Cache)
    container.register(_Repo)
    container.register(_Service)
    svc = container.resolve(_Service)
    assert isinstance(svc, _Service)
    assert isinstance(svc.repo, _Repo)
    assert isinstance(svc.repo.db, _Db)
    assert isinstance(svc.cache, _Cache)


def test_singletons_independent_across_containers() -> None:
    one = Container()
    two = Container()
    one.register(_Db)
    two.register(_Db)
    assert one.resolve(_Db) is not two.resolve(_Db)


def test_iter_singletons_yields_in_first_resolve_order() -> None:
    container = Container()
    container.register(_Db)
    container.register(_Cache)
    container.register(_Logger)
    container.resolve(_Logger)
    container.resolve(_Db)
    container.resolve(_Cache)
    types_in_order = [type(x) for x in container.iter_singletons()]
    assert types_in_order == [_Logger, _Db, _Cache]


def test_iter_singletons_empty_when_no_resolves() -> None:
    container = Container()
    container.register(_Db)
    assert list(container.iter_singletons()) == []
