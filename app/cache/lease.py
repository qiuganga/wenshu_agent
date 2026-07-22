from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.cache.key_builder import CacheKeyBuilder
from app.cache.models import CacheIdentity
from app.core.telemetry import telemetry_manager

RELEASE_LEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class CacheLease:
    def __init__(
        self,
        *,
        redis_client: Callable[[], Any],
        key_builder: CacheKeyBuilder,
        ttl_seconds: int,
        wait_timeout_seconds: float,
    ) -> None:
        self.redis_client = redis_client
        self.key_builder = key_builder
        self.ttl_seconds = ttl_seconds
        self.wait_timeout_seconds = wait_timeout_seconds

    def _client(self) -> Any | None:
        return self.redis_client()

    async def acquire(self, identity: CacheIdentity) -> str | None:
        client = self._client()
        if client is None:
            return None
        owner = secrets.token_urlsafe(16)
        key = self.key_builder.lease_key(identity)
        with telemetry_manager.span("cache.lease", {"cache_type": "lease", "scope_hash": identity.scope_hash}):
            acquired = await client.set(key, owner, ex=self.ttl_seconds, nx=True)
        if acquired:
            telemetry_manager.set_cache_lease_active(1)
            return owner
        telemetry_manager.increment_counter("cache_lease_contention_total", attributes={"cache_type": "lease"})
        return None

    async def release(self, identity: CacheIdentity, owner: str | None) -> None:
        if not owner:
            return
        client = self._client()
        if client is None:
            return
        await client.eval(RELEASE_LEASE_LUA, 1, self.key_builder.lease_key(identity), owner)
        telemetry_manager.set_cache_lease_active(0)

    async def wait_for_fill(
        self,
        identity: CacheIdentity,
        lookup: Callable[[], Awaitable[Any]],
        *,
        poll_seconds: float = 0.05,
    ) -> Any | None:
        if self._client() is None:
            return None
        deadline = time.perf_counter() + self.wait_timeout_seconds
        while time.perf_counter() < deadline:
            result = await lookup()
            if getattr(result, "hit", False):
                return result
            await asyncio.sleep(min(poll_seconds, max(0.0, deadline - time.perf_counter())))
        return None
