from app.governance.complexity import ComplexityLevel
from app.governance.load_shedding import LoadSheddingController, LoadSignals


def test_load_shedding_protects_health_recovery_and_cache_hits() -> None:
    controller = LoadSheddingController(active_query_threshold=1, queue_depth_threshold=1, retry_after_seconds=5)

    assert controller.decide(LoadSignals(active_queries=10, health_check=True)).allowed is True
    assert controller.decide(LoadSignals(active_queries=10, recovery_request=True)).allowed is True
    assert controller.decide(LoadSignals(active_queries=10, cache_hit=True)).allowed is True


def test_load_shedding_rejects_low_priority_heavy_overload() -> None:
    controller = LoadSheddingController(active_query_threshold=1, queue_depth_threshold=1, retry_after_seconds=5)

    decision = controller.decide(LoadSignals(active_queries=1, complexity=ComplexityLevel.HEAVY))

    assert decision.allowed is False
    assert decision.code == "SERVICE_OVERLOADED"
    assert decision.retry_after_seconds == 5
