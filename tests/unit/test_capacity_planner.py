from app.governance.capacity import CapacityPlanner, CapacitySignals


def test_capacity_planner_respects_min_max_and_reports_saturation() -> None:
    planner = CapacityPlanner(target_utilization=0.7, min_replicas=2, max_replicas=5)

    recommendation = planner.recommend(
        CapacitySignals(
            qps=20,
            concurrent_requests=10,
            p95_latency_seconds=1,
            cache_hit_rate=0.1,
            rejection_rate=0.1,
            average_token_usage=1000,
            agent_steps=5,
            handoff_count=1,
        )
    )

    assert 2 <= recommendation.recommended_replicas <= 5
    assert "high_rejection_rate" in recommendation.reason_codes
    assert recommendation.saturation_ratio > 0
