from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.governance.common import GovernanceError, stable_hash


@dataclass(frozen=True)
class QuotaRule:
    quota_type: str
    limit: int
    period_seconds: int


@dataclass
class QuotaManager:
    key_prefix: str
    rules: list[QuotaRule] = field(default_factory=list)
    redis_client: object | None = None

    def __post_init__(self) -> None:
        self._local: dict[str, tuple[int, float]] = {}

    def check_and_consume(self, *, user_id: str, tenant_id: str | None, amount: int = 1) -> None:
        for scope, raw_scope in (("user", user_id), ("tenant", tenant_id or "default"), ("global", "global")):
            for rule in self.rules:
                key = self._key(scope, raw_scope, rule)
                current, expires_at = self._local.get(key, (0, time.time() + rule.period_seconds))
                if time.time() >= expires_at:
                    current, expires_at = 0, time.time() + rule.period_seconds
                if current + amount > rule.limit:
                    raise GovernanceError(
                        self._error_code(rule.quota_type),
                        "Quota exceeded",
                        details={"quota_type": rule.quota_type},
                    )
                self._local[key] = (current + amount, expires_at)

    def _key(self, scope: str, raw_scope: str, rule: QuotaRule) -> str:
        scope_hash = stable_hash(raw_scope)
        period = int(time.time() // rule.period_seconds)
        return f"{self.key_prefix}:quota:{scope}:{scope_hash}:{rule.quota_type}:{period}"

    @staticmethod
    def _error_code(quota_type: str) -> str:
        mapping = {
            "requests": "REQUEST_QUOTA_EXCEEDED",
            "concurrency": "CONCURRENCY_QUOTA_EXCEEDED",
            "tokens": "TOKEN_QUOTA_EXCEEDED",
            "cost": "COST_QUOTA_EXCEEDED",
            "agent_steps": "AGENT_STEP_LIMIT_EXCEEDED",
            "handoffs": "HANDOFF_LIMIT_EXCEEDED",
        }
        return mapping.get(quota_type, "REQUEST_QUOTA_EXCEEDED")
