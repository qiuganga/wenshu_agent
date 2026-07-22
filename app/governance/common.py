from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

SAFE_DETAIL_KEYS = {
    "budget_status",
    "complexity_level",
    "cost_bucket",
    "error_budget_status",
    "load_shed_reason",
    "pricing_version",
    "quota_type",
    "retry_after_seconds",
    "route_reason",
    "slo_name",
    "slo_status",
    "usage_source",
}


def stable_hash(value: str | None) -> str:
    normalized = (value or "anonymous").strip() or "anonymous"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class GovernanceError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        safe_details = {"error_code": error_code, "retryable": retryable}
        if details:
            safe_details.update({key: value for key, value in details.items() if key in SAFE_DETAIL_KEYS})
        self.details = safe_details


@dataclass(frozen=True)
class GovernanceDecision:
    allowed: bool
    code: str = "OK"
    reason_codes: list[str] = field(default_factory=list)
    retry_after_seconds: int | None = None

    def require_allowed(self) -> None:
        if not self.allowed:
            raise GovernanceError(self.code, self.code, details={"load_shed_reason": ",".join(self.reason_codes)})
