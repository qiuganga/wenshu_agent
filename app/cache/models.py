from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CacheScope:
    tenant_id: str = "default"
    user_id: str = "anonymous"
    permission_scope_hash: str = ""
    data_source_id: str = "default"
    database_id: str = "default"
    locale: str = "zh-CN"
    model_name: str = ""
    prompt_name: str = "interpret_result"
    prompt_version: str = "v1"
    prompt_template_hash: str = ""
    schema_version: int = CACHE_SCHEMA_VERSION
    data_version: str = "v1"
    cache_namespace_version: str = "v1"


@dataclass(frozen=True)
class NormalizedQuery:
    normalized_query: str
    query_hash: str


@dataclass(frozen=True)
class CacheIdentity:
    scope: CacheScope
    scope_hash: str
    normalized_query: str
    query_hash: str


@dataclass(frozen=True)
class CacheEntry:
    schema_version: int
    cache_entry_id: str
    query_hash: str
    scope_hash: str
    payload: dict[str, Any]
    created_at: str
    expires_at: str
    data_version: str
    prompt_version: str
    prompt_template_hash: str
    model_name: str
    payload_hash: str
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        return datetime.fromisoformat(self.expires_at) <= datetime.now(UTC)


@dataclass(frozen=True)
class CacheLookupResult:
    hit: bool
    cache_type: Literal["exact", "semantic"] | None = None
    entry: CacheEntry | None = None
    similarity_score: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CacheWriteDecision:
    allowed: bool
    reason: str = "allowed"


@dataclass
class CacheRuntimeContext:
    identity: CacheIdentity
    final_payload: dict[str, Any] | None = None
    cache_hit: CacheLookupResult | None = None
    cache_type: str | None = None
    lease_owner: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
