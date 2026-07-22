from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.cache.exact_cache import ExactCache
from app.cache.key_builder import CacheKeyBuilder, permission_scope_hash
from app.cache.lease import CacheLease
from app.cache.models import CacheIdentity, CacheLookupResult, CacheScope
from app.cache.policy import CachePolicy
from app.cache.sanitizer import CachePayloadSanitizer
from app.cache.semantic_cache import SemanticCache
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.config.app_config import app_config
from app.core.telemetry import telemetry_manager
from app.llm.model_router import model_router
from app.llm.prompt_manager import prompt_template_manager


@dataclass(frozen=True)
class CacheLookupOutcome:
    result: CacheLookupResult
    payload: dict[str, Any] | None = None


class QueryCacheService:
    def __init__(
        self,
        *,
        exact_cache: ExactCache,
        semantic_cache: SemanticCache | None,
        lease: CacheLease,
        key_builder: CacheKeyBuilder,
        policy: CachePolicy,
        enabled: bool,
        exact_enabled: bool,
        semantic_enabled: bool,
    ) -> None:
        self.exact_cache = exact_cache
        self.semantic_cache = semantic_cache
        self.lease = lease
        self.key_builder = key_builder
        self.policy = policy
        self.enabled = enabled
        self.exact_enabled = exact_enabled
        self.semantic_enabled = semantic_enabled

    @classmethod
    def from_app_config(cls) -> QueryCacheService:
        sanitizer = CachePayloadSanitizer(max_entry_bytes=app_config.cache.max_entry_bytes)
        key_builder = CacheKeyBuilder(redis_prefix=app_config.redis.key_prefix)
        exact = ExactCache(
            redis_client=lambda: redis_client_manager.client,
            key_builder=key_builder,
            ttl_seconds=app_config.cache.exact_ttl_seconds,
            sanitizer=sanitizer,
        )
        semantic = SemanticCache(
            qdrant_client=lambda: qdrant_client_manager.client,
            embedding_client=lambda: embedding_client_manager.client,
            collection_name=app_config.cache.semantic_collection_name,
            vector_size=app_config.qdrant.embedding_size,
            ttl_seconds=app_config.cache.semantic_ttl_seconds,
            threshold=app_config.cache.semantic_similarity_threshold,
            top_k=app_config.cache.semantic_top_k,
            sanitizer=sanitizer,
        )
        lease = CacheLease(
            redis_client=lambda: redis_client_manager.client,
            key_builder=key_builder,
            ttl_seconds=app_config.cache.lease_ttl_seconds,
            wait_timeout_seconds=app_config.cache.lease_wait_timeout_seconds,
        )
        policy = CachePolicy(
            max_entry_bytes=app_config.cache.max_entry_bytes,
            cache_safe_final_summary=app_config.cache.cache_safe_final_summary,
        )
        return cls(
            exact_cache=exact,
            semantic_cache=semantic,
            lease=lease,
            key_builder=key_builder,
            policy=policy,
            enabled=app_config.cache.enabled and app_config.cache.cache_safe_final_summary,
            exact_enabled=app_config.cache.exact_enabled,
            semantic_enabled=app_config.cache.semantic_enabled,
        )

    def build_identity(
        self,
        *,
        query: str,
        user_id: str,
        tenant_id: str | None = None,
        permissions: list[str] | None = None,
        data_source_id: str | None = None,
        database_id: str | None = None,
        locale: str | None = None,
    ) -> CacheIdentity:
        prompt_hash = ""
        try:
            prompt_hash = prompt_template_manager.metadata("interpret_result").template_hash
        except Exception:
            prompt_hash = ""
        scope = CacheScope(
            tenant_id=tenant_id or "default",
            user_id=user_id or "anonymous",
            permission_scope_hash=permission_scope_hash(permissions),
            data_source_id=data_source_id or "default",
            database_id=database_id or "default",
            locale=locale or "zh-CN",
            model_name=model_router.primary_model,
            prompt_name="interpret_result",
            prompt_version=app_config.prompt.default_version,
            prompt_template_hash=prompt_hash,
            data_version=app_config.cache.data_version,
            cache_namespace_version=app_config.cache.namespace_version,
        )
        return self.key_builder.identity(query, scope)

    async def lookup(self, identity: CacheIdentity) -> CacheLookupOutcome:
        if not self.enabled:
            return CacheLookupOutcome(CacheLookupResult(False, reason="cache_disabled"))
        telemetry_manager.increment_counter("cache_lookup_total", attributes={"cache_type": "all"})
        with telemetry_manager.span(
            "cache.lookup",
            {"scope_hash": identity.scope_hash, "query_hash": identity.query_hash},
        ):
            if self.exact_enabled:
                exact = await self.exact_cache.load(identity)
                if exact.hit and exact.entry is not None:
                    return CacheLookupOutcome(exact, self._hit_payload(exact))
            if self.semantic_enabled and self.semantic_cache is not None:
                semantic = await self.semantic_cache.lookup(identity)
                if semantic.hit and semantic.entry is not None:
                    return CacheLookupOutcome(semantic, self._hit_payload(semantic))
        return CacheLookupOutcome(CacheLookupResult(False, reason="miss"))

    async def acquire_lease(self, identity: CacheIdentity) -> str | None:
        if not self.enabled:
            return None
        return await self.lease.acquire(identity)

    async def wait_for_fill(self, identity: CacheIdentity) -> CacheLookupOutcome | None:
        if not self.enabled:
            return None
        result = await self.lease.wait_for_fill(identity, lambda: self.lookup(identity))
        return result

    async def release_lease(self, identity: CacheIdentity, owner: str | None) -> None:
        await self.lease.release(identity, owner)

    async def write(
        self,
        *,
        identity: CacheIdentity,
        payload: dict[str, Any],
        final_status: str,
        metadata: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        decision = self.policy.can_write(final_status=final_status, payload=payload, metadata=metadata)
        if not decision.allowed:
            telemetry_manager.increment_counter("cache_write_failed_total", attributes={"cache_type": "policy"})
            return
        try:
            if self.exact_enabled:
                await self.exact_cache.save(identity, payload)
            if self.semantic_enabled and self.semantic_cache is not None:
                await self.semantic_cache.save(identity, payload)
        except Exception:
            telemetry_manager.increment_counter("cache_write_failed_total", attributes={"cache_type": "all"})

    def _hit_payload(self, result: CacheLookupResult) -> dict[str, Any]:
        assert result.entry is not None
        return {
            **result.entry.payload,
            "cache_hit": True,
            "cache_type": result.cache_type,
        }


query_cache_service = QueryCacheService.from_app_config()
