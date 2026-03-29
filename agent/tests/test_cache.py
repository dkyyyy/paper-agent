"""Tests for Redis-backed search cache."""

import fnmatch

import pytest

from app.services.cache import SearchCache


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                deleted += 1
        return deleted

    def scan_iter(self, match=None):
        for key in list(self.store.keys()):
            if match is None or fnmatch.fnmatch(key, match):
                yield key


class BrokenRedis:
    def get(self, key):
        raise RuntimeError("redis down")

    def setex(self, key, ttl, value):
        raise RuntimeError("redis down")

    def delete(self, *keys):
        raise RuntimeError("redis down")

    def scan_iter(self, match=None):
        raise RuntimeError("redis down")


@pytest.fixture
def cache():
    return SearchCache(ttl=60, client=FakeRedis())


def test_cache_miss(cache):
    result = cache.get("arxiv_search", {"query": "nonexistent"})
    assert result is None


def test_cache_set_and_get(cache):
    params = {"query": "RAG", "max_results": 10}
    data = [{"title": "Paper 1"}, {"title": "Paper 2"}]

    cache.set("arxiv_search", params, data)
    result = cache.get("arxiv_search", params)

    assert result is not None
    assert len(result) == 2
    assert result[0]["title"] == "Paper 1"


def test_cache_invalidate(cache):
    params = {"query": "test"}
    cache.set("s2_search", params, [{"title": "X"}])
    cache.invalidate("s2_search", params)
    assert cache.get("s2_search", params) is None


def test_cache_key_deterministic(cache):
    key1 = cache._make_key("tool", {"a": 1, "b": 2})
    key2 = cache._make_key("tool", {"b": 2, "a": 1})
    assert key1 == key2


def test_cache_clear_all_filtered(cache):
    cache.set("arxiv_search", {"query": "a"}, [{"title": "A"}])
    cache.set("s2_search", {"query": "b"}, [{"title": "B"}])

    deleted = cache.clear_all("arxiv_search")

    assert deleted == 1
    assert cache.get("arxiv_search", {"query": "a"}) is None
    assert cache.get("s2_search", {"query": "b"}) is not None


def test_cache_graceful_when_redis_unavailable():
    cache = SearchCache(ttl=60, client=BrokenRedis())

    assert cache.get("arxiv_search", {"query": "x"}) is None
    cache.set("arxiv_search", {"query": "x"}, [{"title": "X"}])
    cache.invalidate("arxiv_search", {"query": "x"})
    assert cache.clear_all() == 0