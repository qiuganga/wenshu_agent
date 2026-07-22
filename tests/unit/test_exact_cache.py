import asyncio

import pytest

from app.cache.exact_cache import ExactCache
from app.cache.key_builder import CacheKeyBuilder
from app.cache.models import CacheScope
from app.cache.sanitizer import CachePayloadSanitizer


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.deleted = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, keepttl=False, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.deleted.append(key)
            self.values.pop(key, None)
        return len(keys)

    async def scan(self, cursor=0, match=None, count=100):
        keys = [key for key in self.values if match is None or key.startswith(match.rstrip("*"))]
        return 0, keys


@pytest.mark.asyncio
async def test_exact_cache_save_load_and_scope_validation():
    redis = FakeRedis()
    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("hello", CacheScope(user_id="u1"))
    cache = ExactCache(
        redis_client=lambda: redis,
        key_builder=builder,
        ttl_seconds=30,
        sanitizer=CachePayloadSanitizer(),
    )

    await cache.save(identity, {"final_answer": "ok", "result_summary": {"row_count": 1}})
    result = await cache.load(identity)
    other = await cache.load(builder.identity("hello", CacheScope(user_id="u2")))

    assert result.hit is True
    assert result.entry is not None
    assert result.entry.payload["final_answer"] == "ok"
    assert other.hit is False


@pytest.mark.asyncio
async def test_exact_cache_corrupt_entry_is_deleted():
    redis = FakeRedis()
    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("hello", CacheScope(user_id="u1"))
    key = builder.exact_key(identity)
    redis.values[key] = "{not-json"
    cache = ExactCache(
        redis_client=lambda: redis,
        key_builder=builder,
        ttl_seconds=30,
        sanitizer=CachePayloadSanitizer(),
    )

    result = await cache.load(identity)

    assert result.hit is False
    assert key in redis.deleted


@pytest.mark.asyncio
async def test_exact_cache_redis_failure_is_miss():
    class BrokenRedis(FakeRedis):
        async def get(self, key):
            raise RuntimeError("redis down")

    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("hello", CacheScope(user_id="u1"))
    cache = ExactCache(
        redis_client=lambda: BrokenRedis(),
        key_builder=builder,
        ttl_seconds=30,
        sanitizer=CachePayloadSanitizer(),
    )

    result = await cache.load(identity)

    assert result.hit is False
    await asyncio.sleep(0)
