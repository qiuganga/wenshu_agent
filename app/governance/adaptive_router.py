from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.governance.common import GovernanceError
from app.governance.complexity import ComplexityLevel


@dataclass(frozen=True)
class ModelCandidate:
    model_name: str
    tier: str
    capabilities: set[str] = field(default_factory=set)
    max_context_tokens: int = 16000
    cost_rank: int = 1
    healthy: bool = True
    health_checked_at: float = 0


@dataclass(frozen=True)
class AdaptiveRoute:
    model_name: str
    reason_codes: list[str]
    fallback_used: bool = False
    degraded: bool = False


class AdaptiveModelRouter:
    def __init__(self, *, health_ttl_seconds: float = 60) -> None:
        self.health_ttl_seconds = health_ttl_seconds

    def route(
        self,
        *,
        complexity: ComplexityLevel,
        candidates: list[ModelCandidate],
        required_capabilities: set[str] | None = None,
        remaining_tokens: int,
        remaining_cost_minor_units: int,
        structured_output_required: bool = False,
    ) -> AdaptiveRoute:
        required = set(required_capabilities or ())
        viable = [
            item
            for item in candidates
            if self._health_valid(item)
            and item.healthy
            and required.issubset(item.capabilities)
            and (not structured_output_required or "structured_output" in item.capabilities)
            and item.max_context_tokens >= remaining_tokens
        ]
        if not viable:
            raise GovernanceError("MODEL_ROUTE_UNAVAILABLE", "No model satisfies routing constraints")
        if remaining_cost_minor_units <= 0:
            selected = sorted(viable, key=lambda item: (item.cost_rank, item.model_name))[0]
            return AdaptiveRoute(selected.model_name, ["budget_degraded", "lowest_cost"], degraded=True)
        if complexity == ComplexityLevel.SIMPLE:
            selected = sorted(viable, key=lambda item: (item.cost_rank, item.model_name))[0]
            return AdaptiveRoute(selected.model_name, ["simple_low_cost"])
        if complexity in {ComplexityLevel.COMPLEX, ComplexityLevel.HEAVY}:
            high_tier = [item for item in viable if item.tier in {"high", "premium"}]
            if high_tier:
                selected = sorted(high_tier, key=lambda item: (item.cost_rank, item.model_name))[0]
                return AdaptiveRoute(selected.model_name, [f"{complexity.lower()}_capable"])
        selected = sorted(viable, key=lambda item: (item.tier != "standard", item.cost_rank, item.model_name))[0]
        return AdaptiveRoute(selected.model_name, ["standard_default"])

    def _health_valid(self, candidate: ModelCandidate) -> bool:
        if candidate.health_checked_at <= 0:
            return True
        return time.time() - candidate.health_checked_at <= self.health_ttl_seconds
