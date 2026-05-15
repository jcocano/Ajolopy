"""Tests for :class:`ajolopy.eval.metrics.JudgeCache`."""

from ajolopy.eval.metrics import JudgeCache


def test_initial_cache_is_empty() -> None:
    cache = JudgeCache()
    assert len(cache) == 0


def test_set_and_get() -> None:
    cache = JudgeCache()
    cache.set("k1", 0.42)
    assert cache.get("k1") == 0.42
    assert "k1" in cache


def test_get_missing_returns_none() -> None:
    cache = JudgeCache()
    assert cache.get("missing") is None


def test_clear_empties() -> None:
    cache = JudgeCache()
    cache.set("k1", 1.0)
    cache.set("k2", 0.0)
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
    assert cache.get("k1") is None
