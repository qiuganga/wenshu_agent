from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CapacitySignals:
    qps: float
    concurrent_requests: int
    p95_latency_seconds: float
    cache_hit_rate: float
    rejection_rate: float
    average_token_usage: int
    agent_steps: int
    handoff_count: int


@dataclass(frozen=True)
class CapacityRecommendation:
    estimated_instance_capacity: float
    recommended_replicas: int
    saturation_ratio: float
    reason_codes: list[str]


class CapacityPlanner:
    def __init__(
        self,
        *,
        target_utilization: float,
        min_replicas: int,
        max_replicas: int,
        cooldown_seconds: int = 60,
    ) -> None:
        self.target_utilization = target_utilization
        self.min_replicas = min_replicas
        self.max_replicas = max_replicas
        self.cooldown_seconds = cooldown_seconds

    def recommend(self, signals: CapacitySignals) -> CapacityRecommendation:
        effective_latency = max(0.001, signals.p95_latency_seconds)
        estimated_capacity = max(1.0, 1 / effective_latency)
        demand = max(signals.qps, float(signals.concurrent_requests) / effective_latency)
        raw_replicas = math.ceil(demand / max(0.01, estimated_capacity * self.target_utilization))
        replicas = min(self.max_replicas, max(self.min_replicas, raw_replicas))
        saturation = min(10.0, demand / max(1.0, estimated_capacity * replicas))
        reasons: list[str] = []
        if saturation > self.target_utilization:
            reasons.append("high_saturation")
        if signals.rejection_rate > 0.05:
            reasons.append("high_rejection_rate")
        if signals.cache_hit_rate < 0.2:
            reasons.append("low_cache_hit_rate")
        return CapacityRecommendation(estimated_capacity, replicas, saturation, reasons or ["within_capacity"])
