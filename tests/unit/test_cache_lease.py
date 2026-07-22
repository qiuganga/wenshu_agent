import pytest

from app.cache.key_builder import CacheKeyBuilder
from app.cache.lease import RELEASE_LEASE_LUA, CacheLease
from app.cache.models import CacheLookupResult, CacheScope


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, keys_count, key, owner):
        assert script == RELEASE_LEASE_LUA
        if self.values.get(key) == owner:
            self.values.pop(key, None)
            return 1
        return 0


@pytest.mark.asyncio
async def test_cache_lease_has_single_owner_and_owner_only_release():
    redis = FakeRedis()
    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("hello", CacheScope(user_id="u1"))
    lease = CacheLease(redis_client=lambda: redis, key_builder=builder, ttl_seconds=30, wait_timeout_seconds=0.01)

    owner = await lease.acquire(identity)
    second = await lease.acquire(identity)
    await lease.release(identity, "wrong-owner")
    still_blocked = await lease.acquire(identity)
    await lease.release(identity, owner)
    after_release = await lease.acquire(identity)

    assert owner is not None
    assert second is None
    assert still_blocked is None
    assert after_release is not None


@pytest.mark.asyncio
async def test_cache_lease_wait_for_fill_reads_owner_result():
    redis = FakeRedis()
    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("hello", CacheScope(user_id="u1"))
    lease = CacheLease(redis_client=lambda: redis, key_builder=builder, ttl_seconds=30, wait_timeout_seconds=0.1)
    calls = 0

    async def lookup():
        nonlocal calls
        calls += 1
        return CacheLookupResult(calls > 1, cache_type="exact")

    result = await lease.wait_for_fill(identity, lookup)

    assert result is not None
    assert result.hit is True
