from __future__ import annotations

from dataclasses import dataclass

from app.governance.common import GovernanceDecision
from app.governance.complexity import ComplexityLevel


@dataclass(frozen=True)
class LoadSignals:
    active_queries: int
    queue_depth: int = 0
    admission_utilization: float = 0
    redis_available: bool = True
    dependency_healthy: bool = True
    error_budget_status: str = "HEALTHY"
    request_priority: str = "normal"
    complexity: ComplexityLevel = ComplexityLevel.STANDARD
    cache_hit: bool = False
    recovery_request: bool = False
    health_check: bool = False


class LoadSheddingController:
    def __init__(self, *, active_query_threshold: int, queue_depth_threshold: int, retry_after_seconds: int) -> None:
        self.active_query_threshold = active_query_threshold
        self.queue_depth_threshold = queue_depth_threshold
        self.retry_after_seconds = retry_after_seconds

    def decide(self, signals: LoadSignals) -> GovernanceDecision:
        if signals.health_check or signals.recovery_request or signals.cache_hit:
            return GovernanceDecision(True, reason_codes=["protected_request"])
        if not signals.redis_available or not signals.dependency_healthy:
            return GovernanceDecision(False, "SERVICE_OVERLOADED", ["dependency_unavailable"], self.retry_after_seconds)
        overloaded = (
            signals.active_queries >= self.active_query_threshold
            or signals.queue_depth >= self.queue_depth_threshold
            or signals.admission_utilization >= 1
            or signals.error_budget_status == "EXHAUSTED"
        )
        if overloaded and signals.complexity == ComplexityLevel.HEAVY and signals.request_priority != "high":
            return GovernanceDecision(False, "SERVICE_OVERLOADED", ["heavy_request_shed"], self.retry_after_seconds)
        return GovernanceDecision(True, reason_codes=["accepted"])
