from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.cache.models import CACHE_SCHEMA_VERSION, CacheEntry, CacheIdentity, CacheLookupResult
from app.cache.sanitizer import CachePayloadSanitizer, payload_hash
from app.cache.semantic_guard import SemanticMatchGuard
from app.core.telemetry import telemetry_manager


class SemanticCache:
    def __init__(
        self,
        *,
        qdrant_client: Any,
        embedding_client: Any,
        collection_name: str,
        vector_size: int,
        ttl_seconds: int,
        threshold: float,
        top_k: int,
        sanitizer: CachePayloadSanitizer,
        guard: SemanticMatchGuard | None = None,
    ) -> None:
        self._qdrant_client = qdrant_client
        self._embedding_client = embedding_client
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.ttl_seconds = ttl_seconds
        self.threshold = threshold
        self.top_k = top_k
        self.sanitizer = sanitizer
        self.guard = guard or SemanticMatchGuard()

    async def ensure_collection(self) -> None:
        qdrant_client = self.qdrant_client
        if qdrant_client is None:
            return
        if not await qdrant_client.collection_exists(self.collection_name):
            await qdrant_client.create_collection(
                self.collection_name,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )

    @property
    def qdrant_client(self) -> Any:
        return self._qdrant_client() if callable(self._qdrant_client) else self._qdrant_client

    @property
    def embedding_client(self) -> Any:
        return self._embedding_client() if callable(self._embedding_client) else self._embedding_client

    async def lookup(self, identity: CacheIdentity) -> CacheLookupResult:
        qdrant_client = self.qdrant_client
        embedding_client = self.embedding_client
        if qdrant_client is None or embedding_client is None:
            return CacheLookupResult(False, reason="semantic_unavailable")
        try:
            started = time.perf_counter()
            with telemetry_manager.span("retrieval.embedding", {"cache_type": "semantic"}):
                embedding = await embedding_client.aembed_query(identity.normalized_query)
            telemetry_manager.record_histogram("embedding_latency_seconds", time.perf_counter() - started)
            await self.ensure_collection()
            query_filter = Filter(
                must=[
                    FieldCondition(key="scope_hash", match=MatchValue(value=identity.scope_hash)),
                    FieldCondition(key="data_version", match=MatchValue(value=identity.scope.data_version)),
                    FieldCondition(key="prompt_version", match=MatchValue(value=identity.scope.prompt_version)),
                    FieldCondition(key="model_name", match=MatchValue(value=identity.scope.model_name)),
                ]
            )
            with telemetry_manager.span(
                "cache.semantic.lookup",
                {
                    "cache_type": "semantic",
                    "scope_hash": identity.scope_hash,
                    "query_hash": identity.query_hash,
                    "threshold": self.threshold,
                },
            ):
                search_started = time.perf_counter()
                result = await qdrant_client.query_points(
                    collection_name=self.collection_name,
                    query=embedding,
                    query_filter=query_filter,
                    score_threshold=self.threshold,
                    limit=self.top_k,
                )
                telemetry_manager.record_histogram(
                    "semantic_search_latency_seconds", time.perf_counter() - search_started
                )
        except Exception:
            telemetry_manager.increment_counter("cache_miss_total", attributes={"cache_type": "semantic"})
            return CacheLookupResult(False, reason="semantic_error")
        for point in result.points:
            payload = point.payload or {}
            if not self.guard.allow(identity.normalized_query, str(payload.get("normalized_query", ""))):
                telemetry_manager.increment_counter(
                    "semantic_cache_rejected_total", attributes={"cache_type": "semantic"}
                )
                continue
            try:
                entry = self._entry_from_payload(payload, identity)
            except Exception:
                continue
            telemetry_manager.increment_counter("semantic_cache_hit_total", attributes={"cache_type": "semantic"})
            telemetry_manager.increment_counter("cache_hit_total", attributes={"cache_type": "semantic"})
            telemetry_manager.record_histogram("semantic_similarity_score", float(point.score))
            return CacheLookupResult(True, "semantic", entry, similarity_score=float(point.score))
        telemetry_manager.increment_counter("cache_miss_total", attributes={"cache_type": "semantic"})
        return CacheLookupResult(False, reason="semantic_miss")

    async def save(self, identity: CacheIdentity, payload: dict[str, Any]) -> None:
        qdrant_client = self.qdrant_client
        embedding_client = self.embedding_client
        if qdrant_client is None or embedding_client is None:
            return
        await self.ensure_collection()
        safe_payload = self.sanitizer.sanitize_payload(payload)
        embedding = await embedding_client.aembed_query(identity.normalized_query)
        now = datetime.now(UTC)
        expires_at = now.timestamp() + self.ttl_seconds
        qdrant_payload = {
            "cache_entry_id": identity.query_hash,
            "query_hash": identity.query_hash,
            "scope_hash": identity.scope_hash,
            "normalized_query": identity.normalized_query,
            "created_at": now.isoformat(),
            "expires_at": datetime.fromtimestamp(expires_at, UTC).isoformat(),
            "data_version": identity.scope.data_version,
            "prompt_version": identity.scope.prompt_version,
            "prompt_template_hash": identity.scope.prompt_template_hash,
            "model_name": identity.scope.model_name,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "payload": safe_payload,
            "payload_hash": payload_hash(safe_payload),
        }
        await qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=str(uuid5(NAMESPACE_URL, identity.query_hash)),
                    vector=embedding,
                    payload=qdrant_payload,
                )
            ],
        )

    def _entry_from_payload(self, payload: dict[str, Any], identity: CacheIdentity) -> CacheEntry:
        if payload.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("schema mismatch")
        expires_at = str(payload["expires_at"])
        if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
            raise ValueError("expired")
        if payload.get("scope_hash") != identity.scope_hash:
            raise ValueError("scope mismatch")
        safe_payload = payload.get("payload")
        if not isinstance(safe_payload, dict):
            raise ValueError("payload missing")
        if payload_hash(safe_payload) != payload.get("payload_hash"):
            raise ValueError("payload hash mismatch")
        return CacheEntry(
            schema_version=CACHE_SCHEMA_VERSION,
            cache_entry_id=str(payload["cache_entry_id"]),
            query_hash=str(payload["query_hash"]),
            scope_hash=str(payload["scope_hash"]),
            payload=json.loads(json.dumps(safe_payload)),
            created_at=str(payload["created_at"]),
            expires_at=expires_at,
            data_version=str(payload["data_version"]),
            prompt_version=str(payload["prompt_version"]),
            prompt_template_hash=str(payload["prompt_template_hash"]),
            model_name=str(payload["model_name"]),
            payload_hash=str(payload["payload_hash"]),
        )
