"""Redis-backed cache for search results."""

import hashlib
import json
import logging
from typing import Any

import redis

from app.config import config

logger = logging.getLogger(__name__)


class SearchCache:
    """Cache search results in Redis with TTL."""

    def __init__(self, ttl: int = 3600, client: redis.Redis | None = None):
        self.ttl = ttl
        self._client = client

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(config.redis_url, decode_responses=True)
        return self._client

    @staticmethod
    def _make_key(tool_name: str, params: dict[str, Any]) -> str:
        """Generate a deterministic cache key from tool name and params."""
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        params_hash = hashlib.md5(params_str.encode("utf-8")).hexdigest()
        return f"search:{tool_name}:{params_hash}"

    def get(self, tool_name: str, params: dict[str, Any]) -> Any | None:
        """Get a cached result, returning None on miss or Redis failure."""
        key = self._make_key(tool_name, params)
        try:
            payload = self.client.get(key)
            if payload:
                logger.debug("Cache hit: %s", key)
                return json.loads(payload)
        except Exception as exc:
            logger.warning("Cache get failed: %s", exc)
        return None

    def set(self, tool_name: str, params: dict[str, Any], result: Any) -> None:
        """Cache a result with the configured TTL."""
        key = self._make_key(tool_name, params)
        try:
            self.client.setex(key, self.ttl, json.dumps(result, ensure_ascii=False))
            logger.debug("Cache set: %s", key)
        except Exception as exc:
            logger.warning("Cache set failed: %s", exc)

    def invalidate(self, tool_name: str, params: dict[str, Any]) -> None:
        """Delete a single cache entry."""
        key = self._make_key(tool_name, params)
        try:
            self.client.delete(key)
        except Exception as exc:
            logger.warning("Cache invalidate failed: %s", exc)

    def clear_all(self, tool_name: str | None = None) -> int:
        """Clear all cache entries, optionally filtered by tool name."""
        try:
            pattern = f"search:{tool_name}:*" if tool_name else "search:*"
            keys = list(self.client.scan_iter(match=pattern))
            if keys:
                return self.client.delete(*keys)
        except Exception as exc:
            logger.warning("Cache clear failed: %s", exc)
        return 0


search_cache = SearchCache()