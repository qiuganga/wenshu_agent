from types import SimpleNamespace

import pytest

from app.cache.key_builder import CacheKeyBuilder
from app.cache.models import CacheScope
from app.cache.sanitizer import CachePayloadSanitizer
from app.cache.semantic_cache import SemanticCache
from app.cache.semantic_guard import SemanticMatchGuard


class FakeEmbedding:
    async def aembed_query(self, text):
        return [1.0, 0.0]


class FakeQdrant:
    def __init__(self):
        self.exists = False
        self.points = []
        self.filters = []

    async def collection_exists(self, name):
        return self.exists

    async def create_collection(self, collection_name, vectors_config):
        self.exists = True

    async def upsert(self, collection_name, points):
        self.points.extend(points)

    async def query_points(self, **kwargs):
        self.filters.append(kwargs["query_filter"])
        return SimpleNamespace(points=[SimpleNamespace(payload=point.payload, score=0.95) for point in self.points])


def semantic_cache(qdrant):
    return SemanticCache(
        qdrant_client=qdrant,
        embedding_client=FakeEmbedding(),
        collection_name="semantic_cache_test",
        vector_size=2,
        ttl_seconds=30,
        threshold=0.92,
        top_k=5,
        sanitizer=CachePayloadSanitizer(),
    )


@pytest.mark.asyncio
async def test_semantic_cache_hit_uses_scope_filter_and_safe_payload():
    qdrant = FakeQdrant()
    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("最近 7 天销售额", CacheScope(user_id="u1"))
    cache = semantic_cache(qdrant)

    await cache.save(identity, {"final_answer": "ok", "result_summary": {"row_count": 1}})
    result = await cache.lookup(identity)

    assert result.hit is True
    assert result.cache_type == "semantic"
    assert result.entry is not None
    assert result.entry.payload["final_answer"] == "ok"
    assert qdrant.filters


@pytest.mark.asyncio
async def test_semantic_cache_rejects_number_top_direction_and_negative_conflicts():
    qdrant = FakeQdrant()
    builder = CacheKeyBuilder(redis_prefix="agent")
    source = builder.identity("销售额最高 top 10", CacheScope(user_id="u1"))
    target = builder.identity("销售额最低 top 10", CacheScope(user_id="u1"))
    cache = semantic_cache(qdrant)

    await cache.save(source, {"final_answer": "ok", "result_summary": {"row_count": 1}})
    result = await cache.lookup(target)

    assert result.hit is False


def test_semantic_guard_rejects_date_and_negation_mismatch():
    guard = SemanticMatchGuard()

    assert guard.allow("最近 7 天销售额", "最近 7 天销售额") is True
    assert guard.allow("最近 7 天销售额", "最近 30 天销售额") is False
    assert guard.allow("不要华南销售额", "华南销售额") is False
