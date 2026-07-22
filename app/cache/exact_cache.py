from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.cache.key_builder import CacheKeyBuilder
from app.cache.models import CACHE_SCHEMA_VERSION, CacheEntry, CacheIdentity, CacheLookupResult
from app.cache.sanitizer import CachePayloadSanitizer, payload_hash
from app.core.telemetry import telemetry_manager


class ExactCache:
    def __init__(
        self,
        *,
        redis_client: Callable[[], Any],
        key_builder: CacheKeyBuilder,
        ttl_seconds: int,
        sanitizer: CachePayloadSanitizer,
    ) -> None:
        self.redis_client = redis_client
        self.key_builder = key_builder
        self.ttl_seconds = ttl_seconds
        self.sanitizer = sanitizer

    def _client(self) -> Any | None:
        return self.redis_client()

    async def load(self, identity: CacheIdentity) -> CacheLookupResult:
        client = self._client()
        if client is None:
            return CacheLookupResult(False, reason="redis_unavailable")
        key = self.key_builder.exact_key(identity)
        with telemetry_manager.span(
            "cache.exact.lookup",
            {"cache_type": "exact", "scope_hash": identity.scope_hash, "query_hash": identity.query_hash},
        ):
            try:
                raw = await client.get(key)
            except Exception:
                telemetry_manager.increment_counter("cache_miss_total", attributes={"cache_type": "exact"})
                return CacheLookupResult(False, reason="redis_error")
        if not raw:
            telemetry_manager.increment_counter("cache_miss_total", attributes={"cache_type": "exact"})
            return CacheLookupResult(False, reason="miss")
        try:
            data = json.loads(raw)
            entry = CacheEntry(**data)
            self._validate_entry(entry, identity)
        except Exception:
            with suppress(Exception):
                await client.delete(key)
            telemetry_manager.increment_counter("cache_miss_total", attributes={"cache_type": "exact"})
            return CacheLookupResult(False, reason="corrupt_or_mismatch")
        await client.set(
            key, json.dumps({**entry.__dict__, "hit_count": entry.hit_count + 1}, ensure_ascii=False), keepttl=True
        )
        telemetry_manager.increment_counter("exact_cache_hit_total", attributes={"cache_type": "exact"})
        telemetry_manager.increment_counter("cache_hit_total", attributes={"cache_type": "exact"})
        return CacheLookupResult(True, "exact", entry)

    async def save(self, identity: CacheIdentity, payload: dict[str, Any]) -> CacheEntry | None:
        client = self._client()
        if client is None:
            return None
        safe_payload = self.sanitizer.sanitize_payload(payload)
        now = datetime.now(UTC)
        entry = CacheEntry(
            schema_version=CACHE_SCHEMA_VERSION,
            cache_entry_id=str(uuid4()),
            query_hash=identity.query_hash,
            scope_hash=identity.scope_hash,
            payload=safe_payload,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            data_version=identity.scope.data_version,
            prompt_version=identity.scope.prompt_version,
            prompt_template_hash=identity.scope.prompt_template_hash,
            model_name=identity.scope.model_name,
            payload_hash=payload_hash(safe_payload),
        )
        key = self.key_builder.exact_key(identity)
        with telemetry_manager.span(
            "cache.write",
            {
                "cache_type": "exact",
                "cache_entry_size": len(json.dumps(entry.__dict__, ensure_ascii=False).encode("utf-8")),
            },
        ):
            await client.set(key, json.dumps(entry.__dict__, ensure_ascii=False), ex=self.ttl_seconds)
        telemetry_manager.increment_counter("cache_write_total", attributes={"cache_type": "exact"})
        return entry

    async def invalidate_scope(self, identity: CacheIdentity) -> int:
        client = self._client()
        if client is None:
            return 0
        pattern = f"{self.key_builder.redis_prefix}:cache:exact:{identity.scope_hash}:*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted += await client.delete(*keys)
            if int(cursor) == 0:
                break
        telemetry_manager.increment_counter("cache_invalidated_total", deleted, attributes={"cache_type": "exact"})
        return deleted

    def _validate_entry(self, entry: CacheEntry, identity: CacheIdentity) -> None:
        if entry.schema_version != CACHE_SCHEMA_VERSION:
            raise ValueError("schema mismatch")
        if entry.scope_hash != identity.scope_hash or entry.query_hash != identity.query_hash:
            raise ValueError("identity mismatch")
        if entry.data_version != identity.scope.data_version:
            raise ValueError("data version mismatch")
        if entry.prompt_version != identity.scope.prompt_version:
            raise ValueError("prompt version mismatch")
        if entry.prompt_template_hash != identity.scope.prompt_template_hash:
            raise ValueError("prompt hash mismatch")
        if entry.model_name != identity.scope.model_name:
            raise ValueError("model mismatch")
        if entry.expired:
            raise ValueError("expired")
        if payload_hash(entry.payload) != entry.payload_hash:
            raise ValueError("payload hash mismatch")
