import time

import pytest

from app.governance.adaptive_router import AdaptiveModelRouter, ModelCandidate
from app.governance.common import GovernanceError
from app.governance.complexity import ComplexityLevel


def test_adaptive_router_prefers_low_cost_for_simple() -> None:
    router = AdaptiveModelRouter()
    route = router.route(
        complexity=ComplexityLevel.SIMPLE,
        candidates=[
            ModelCandidate("expensive", "premium", {"chat"}, cost_rank=10),
            ModelCandidate("cheap", "low", {"chat"}, cost_rank=1),
        ],
        required_capabilities={"chat"},
        remaining_tokens=1000,
        remaining_cost_minor_units=100,
    )

    assert route.model_name == "cheap"
    assert route.reason_codes == ["simple_low_cost"]


def test_adaptive_router_uses_capable_model_for_complex_and_rejects_mismatch() -> None:
    router = AdaptiveModelRouter()
    route = router.route(
        complexity=ComplexityLevel.COMPLEX,
        candidates=[
            ModelCandidate("cheap", "low", {"chat"}, cost_rank=1),
            ModelCandidate("strong", "high", {"chat", "structured_output"}, cost_rank=5),
        ],
        required_capabilities={"chat"},
        structured_output_required=True,
        remaining_tokens=1000,
        remaining_cost_minor_units=100,
    )
    assert route.model_name == "strong"

    with pytest.raises(GovernanceError):
        router.route(
            complexity=ComplexityLevel.STANDARD,
            candidates=[ModelCandidate("plain", "standard", {"chat"})],
            required_capabilities={"vision"},
            remaining_tokens=1000,
            remaining_cost_minor_units=100,
        )


def test_adaptive_router_skips_unhealthy_until_ttl_expires() -> None:
    router = AdaptiveModelRouter(health_ttl_seconds=60)
    with pytest.raises(GovernanceError):
        router.route(
            complexity=ComplexityLevel.SIMPLE,
            candidates=[
                ModelCandidate(
                    "unhealthy",
                    "low",
                    {"chat"},
                    healthy=False,
                    health_checked_at=time.time(),
                )
            ],
            required_capabilities={"chat"},
            remaining_tokens=1000,
            remaining_cost_minor_units=100,
        )
