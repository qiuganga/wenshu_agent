import asyncio
from collections import defaultdict

import pytest

from app.service.query_lifecycle import (
    ADMISSION_ACQUIRE_LUA,
    ADMISSION_RELEASE_LUA,
    DEDUP_REGISTER_LUA,
    QueryLifecycleError,
    RedisQueryAdmissionController,
    RedisRequestDedupRegistry,
)


class FakeRedis:
    def __init__(self):
        self.now_ms = 1_000_000
        self.values: dict[str, tuple[str, int | None]] = {}
        self.zsets: dict[str, dict[str, int]] = defaultdict(dict)

    def advance(self, milliseconds: int) -> None:
        self.now_ms += milliseconds

    def _expired(self, expires_at: int | None) -> bool:
        return expires_at is not None and expires_at <= self.now_ms

    def _prune_key(self, key: str) -> None:
        if key in self.values and self._expired(self.values[key][1]):
            self.values.pop(key, None)

    def _zrem_expired(self, key: str, now_ms: int) -> None:
        self.zsets[key] = {member: score for member, score in self.zsets[key].items() if score > now_ms}

    async def eval(self, script: str, numkeys: int, *args):
        keys = args[:numkeys]
        argv = args[numkeys:]
        if script == DEDUP_REGISTER_LUA:
            key = keys[0]
            self._prune_key(key)
            if key in self.values:
                return 0
            self.values[key] = (str(argv[0]), self.now_ms + int(argv[1]))
            return 1
        if script == ADMISSION_ACQUIRE_LUA:
            global_key, user_key, lease_key = keys
            now_ms = int(argv[0])
            expires_at_ms = int(argv[1])
            max_global = int(argv[2])
            max_per_user = int(argv[3])
            user_hash = str(argv[4])
            member = str(argv[5])
            ttl_ms = int(argv[6])
            self._prune_key(lease_key)
            self._zrem_expired(global_key, now_ms)
            self._zrem_expired(user_key, now_ms)
            if lease_key in self.values:
                return ["duplicate", len(self.zsets[global_key]), len(self.zsets[user_key])]
            if len(self.zsets[user_key]) >= max_per_user:
                return ["user_limit", len(self.zsets[global_key]), len(self.zsets[user_key])]
            if len(self.zsets[global_key]) >= max_global:
                return ["global_limit", len(self.zsets[global_key]), len(self.zsets[user_key])]
            self.zsets[global_key][member] = expires_at_ms
            self.zsets[user_key][member] = expires_at_ms
            self.values[lease_key] = (user_hash, self.now_ms + ttl_ms)
            return ["ok", len(self.zsets[global_key]), len(self.zsets[user_key])]
        if script == ADMISSION_RELEASE_LUA:
            global_key, user_key, lease_key = keys
            member = str(argv[0])
            self.zsets[global_key].pop(member, None)
            self.zsets[user_key].pop(member, None)
            self.values.pop(lease_key, None)
            return [len(self.zsets[global_key]), len(self.zsets[user_key])]
        raise AssertionError("unexpected lua script")

    async def exists(self, key: str) -> int:
        self._prune_key(key)
        return int(key in self.values)

    async def set(self, key: str, value: str, *, keepttl: bool = False) -> None:
        self._prune_key(key)
        expires_at = self.values[key][1] if keepttl and key in self.values else None
        self.values[key] = (value, expires_at)


@pytest.mark.asyncio
async def test_redis_dedup_rejects_duplicate_and_preserves_ttl():
    redis = FakeRedis()
    registry = RedisRequestDedupRegistry(
        ttl_seconds=0.1,
        max_entries=100,
        redis_client=lambda: redis,
        key_prefix="test",
    )

    token = await registry.register("request-1")
    with pytest.raises(QueryLifecycleError) as exc_info:
        await registry.register("request-1")

    assert exc_info.value.code == "DUPLICATE_REQUEST"
    await registry.complete(token, "completed")
    redis.advance(99)
    with pytest.raises(QueryLifecycleError):
        await registry.register("request-1")
    redis.advance(1)
    await registry.register("request-1")


@pytest.mark.asyncio
async def test_redis_dedup_survives_service_restart():
    redis = FakeRedis()
    first = RedisRequestDedupRegistry(
        ttl_seconds=30,
        max_entries=100,
        redis_client=lambda: redis,
        key_prefix="test",
    )
    second = RedisRequestDedupRegistry(
        ttl_seconds=30,
        max_entries=100,
        redis_client=lambda: redis,
        key_prefix="test",
    )

    await first.register("request-1")

    with pytest.raises(QueryLifecycleError) as exc_info:
        await second.register("request-1")

    assert exc_info.value.code == "DUPLICATE_REQUEST"


def redis_admission(redis: FakeRedis, *, max_global=1, max_per_user=1, timeout_seconds=0.01):
    return RedisQueryAdmissionController(
        max_global=max_global,
        max_per_user=max_per_user,
        timeout_seconds=timeout_seconds,
        redis_client=lambda: redis,
        key_prefix="test",
        lease_ttl_seconds=30,
    )


@pytest.mark.asyncio
async def test_redis_admission_global_limit_and_release():
    redis = FakeRedis()
    controller = redis_admission(redis, max_global=1, max_per_user=1)
    lease = await controller.acquire(user_id="u1", key="k1")

    with pytest.raises(QueryLifecycleError) as exc_info:
        await controller.acquire(user_id="u2", key="k2")

    assert exc_info.value.details["error_code"] == "QUERY_CONCURRENCY_LIMIT"
    await controller.release(lease)
    second = await controller.acquire(user_id="u2", key="k2")
    await controller.release(second)


@pytest.mark.asyncio
async def test_redis_admission_user_limit_does_not_block_other_users():
    redis = FakeRedis()
    controller = redis_admission(redis, max_global=2, max_per_user=1)
    first = await controller.acquire(user_id="u1", key="k1")
    second = await controller.acquire(user_id="u2", key="k2")

    with pytest.raises(QueryLifecycleError) as exc_info:
        await controller.acquire(user_id="u1", key="k3")

    assert exc_info.value.details["error_code"] == "USER_QUERY_CONCURRENCY_LIMIT"
    await controller.release(first)
    await controller.release(second)


@pytest.mark.asyncio
async def test_redis_admission_concurrent_competition_allows_one_winner():
    redis = FakeRedis()
    controller = redis_admission(redis, max_global=1, max_per_user=1)

    async def acquire(key: str):
        try:
            return await controller.acquire(user_id="u1", key=key)
        except QueryLifecycleError as exc:
            return exc

    results = await asyncio.gather(acquire("k1"), acquire("k2"))

    leases = [result for result in results if not isinstance(result, QueryLifecycleError)]
    errors = [result for result in results if isinstance(result, QueryLifecycleError)]
    assert len(leases) == 1
    assert len(errors) == 1
    assert errors[0].details["error_code"] == "USER_QUERY_CONCURRENCY_LIMIT"
    await controller.release(leases[0])


@pytest.mark.asyncio
async def test_redis_admission_survives_service_restart_until_release_or_ttl():
    redis = FakeRedis()
    first = redis_admission(redis, max_global=1, max_per_user=1)
    second = redis_admission(redis, max_global=1, max_per_user=1)
    lease = await first.acquire(user_id="u1", key="k1")

    with pytest.raises(QueryLifecycleError):
        await second.acquire(user_id="u2", key="k2")

    await first.release(lease)
    await second.acquire(user_id="u2", key="k2")
