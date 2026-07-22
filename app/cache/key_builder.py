from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable

from app.cache.models import CacheIdentity, CacheScope, NormalizedQuery

SPACE_RE = re.compile(r"\s+")


class QueryNormalizer:
    def __init__(self, *, lowercase: bool = False):
        self.lowercase = lowercase

    def normalize(self, query: str) -> str:
        text = unicodedata.normalize("NFKC", query.strip())
        text = SPACE_RE.sub(" ", text)
        if self.lowercase:
            text = text.lower()
        return text

    def normalize_with_hash(self, query: str, stable_scope: str, version_info: str) -> NormalizedQuery:
        normalized_query = self.normalize(query)
        material = json.dumps(
            {
                "normalized_query": normalized_query,
                "scope": stable_scope,
                "version": version_info,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return NormalizedQuery(
            normalized_query=normalized_query,
            query_hash=hashlib.sha256(material.encode("utf-8")).hexdigest(),
        )


def stable_json_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def permission_scope_hash(permissions: Iterable[str] | None) -> str:
    values = sorted(str(item) for item in permissions or [])
    return stable_json_hash(values)


class CacheKeyBuilder:
    def __init__(self, *, redis_prefix: str):
        self.redis_prefix = redis_prefix.rstrip(":")

    @staticmethod
    def scope_hash(scope: CacheScope) -> str:
        return stable_json_hash(scope.__dict__)

    @staticmethod
    def version_info(scope: CacheScope) -> str:
        return stable_json_hash(
            {
                "schema_version": scope.schema_version,
                "data_version": scope.data_version,
                "prompt_version": scope.prompt_version,
                "prompt_template_hash": scope.prompt_template_hash,
                "model_name": scope.model_name,
                "namespace": scope.cache_namespace_version,
            }
        )

    def identity(self, query: str, scope: CacheScope, normalizer: QueryNormalizer | None = None) -> CacheIdentity:
        normalizer = normalizer or QueryNormalizer()
        scope_hash = self.scope_hash(scope)
        normalized = normalizer.normalize_with_hash(query, scope_hash, self.version_info(scope))
        return CacheIdentity(
            scope=scope,
            scope_hash=scope_hash,
            normalized_query=normalized.normalized_query,
            query_hash=normalized.query_hash,
        )

    def exact_key(self, identity: CacheIdentity) -> str:
        return f"{self.redis_prefix}:cache:exact:{identity.scope_hash}:{identity.query_hash}"

    def lease_key(self, identity: CacheIdentity) -> str:
        return f"{self.redis_prefix}:cache:lease:{identity.scope_hash}:{identity.query_hash}"
