# Codex 执行指令 — 任务 6.1：Redis 搜索缓存

## 任务目标

缓存 MCP 工具的搜索结果，相同 query 在 TTL 内直接返回缓存，避免重复调用外部 API。

## 前置依赖

- 任务 3.1 已完成（Python 项目骨架 + config）

## 需要创建的文件

### 1. `agent/app/services/cache.py`

```python
"""Redis 搜索结果缓存。"""

import hashlib
import json
import logging
from typing import Any

import redis

from app.config import config

logger = logging.getLogger(__name__)


class SearchCache:
    """Cache search results in Redis with TTL."""

    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._client = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(config.redis_url, decode_responses=True)
        return self._client

    @staticmethod
    def _make_key(tool_name: str, params: dict) -> str:
        """Generate cache key: search:{tool_name}:{md5(params)}"""
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()
        return f"search:{tool_name}:{params_hash}"

    def get(self, tool_name: str, params: dict) -> Any | None:
        """Get cached result. Returns None on miss."""
        key = self._make_key(tool_name, params)
        try:
            data = self.client.get(key)
            if data:
                logger.debug(f"Cache hit: {key}")
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
        return None

    def set(self, tool_name: str, params: dict, result: Any) -> None:
        """Cache a result with TTL."""
        key = self._make_key(tool_name, params)
        try:
            self.client.setex(key, self.ttl, json.dumps(result, ensure_ascii=False))
            logger.debug(f"Cache set: {key}")
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

    def invalidate(self, tool_name: str, params: dict) -> None:
        """Remove a specific cache entry."""
        key = self._make_key(tool_name, params)
        try:
            self.client.delete(key)
        except Exception as e:
            logger.warning(f"Cache invalidate failed: {e}")

    def clear_all(self, tool_name: str | None = None) -> int:
        """Clear all cache entries, optionally filtered by tool name.

        Returns number of keys deleted.
        """
        try:
            pattern = f"search:{tool_name}:*" if tool_name else "search:*"
            keys = list(self.client.scan_iter(match=pattern))
            if keys:
                return self.client.delete(*keys)
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")
        return 0


# Singleton instance
search_cache = SearchCache()
```

### 2. `agent/app/services/__init__.py`

空文件。

### 3. `agent/tests/test_cache.py`

```python
"""Test search cache (requires Redis on localhost:6379)."""

import pytest
from app.services.cache import SearchCache


@pytest.fixture
def cache():
    c = SearchCache(ttl=60)
    yield c
    c.clear_all()


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
    """Same params in different order should produce same key."""
    key1 = cache._make_key("tool", {"a": 1, "b": 2})
    key2 = cache._make_key("tool", {"b": 2, "a": 1})
    assert key1 == key2
```

## 验收标准

- [ ] 缓存 key 格式：`search:{tool_name}:{md5(params)}`
- [ ] TTL 默认 1 小时
- [ ] 命中缓存时不调用外部 API（调用方负责检查）
- [ ] 支持手动清除缓存（按 tool_name 或全部）
- [ ] 参数顺序不同但内容相同时命中同一缓存
- [ ] Redis 不可用时不崩溃（降级为无缓存）
- [ ] 测试通过

## 提交

```bash
git add agent/app/services/ agent/tests/test_cache.py
git commit -m "feat(agent): implement Redis search result cache

- Cache key: search:{tool}:{md5(params)}, TTL 1h
- Deterministic key generation (sorted params)
- Graceful degradation when Redis unavailable
- Support invalidate and clear_all operations"
```
