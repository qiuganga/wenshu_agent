from app.cache.key_builder import CacheKeyBuilder, QueryNormalizer, permission_scope_hash
from app.cache.models import CacheScope


def test_query_normalizer_preserves_business_tokens():
    normalizer = QueryNormalizer()

    normalized = normalizer.normalize("  查询　2025 年 最近 7 天 不是 华南   销售额  ")

    assert normalized == "查询 2025 年 最近 7 天 不是 华南 销售额"
    assert "2025" in normalized
    assert "7" in normalized
    assert "不是" in normalized


def test_query_hash_is_stable_and_scope_aware():
    builder = CacheKeyBuilder(redis_prefix="agent")
    scope_a = CacheScope(user_id="u1", permission_scope_hash=permission_scope_hash(["read:orders"]))
    scope_b = CacheScope(user_id="u2", permission_scope_hash=permission_scope_hash(["read:orders"]))

    first = builder.identity("查询销售额", scope_a)
    second = builder.identity(" 查询销售额 ", scope_a)
    other = builder.identity("查询销售额", scope_b)

    assert first.query_hash == second.query_hash
    assert first.query_hash != other.query_hash
    assert first.scope_hash != other.scope_hash


def test_cache_key_includes_scope_query_and_namespace():
    builder = CacheKeyBuilder(redis_prefix="agent")
    identity = builder.identity("hello", CacheScope(user_id="u1", cache_namespace_version="v2"))

    key = builder.exact_key(identity)

    assert key == f"agent:cache:exact:{identity.scope_hash}:{identity.query_hash}"
    assert builder.lease_key(identity) == f"agent:cache:lease:{identity.scope_hash}:{identity.query_hash}"
