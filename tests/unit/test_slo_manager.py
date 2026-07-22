from app.governance.slo import SLOManager


def test_slo_manager_tracks_latency_and_availability_without_business_denies() -> None:
    manager = SLOManager(availability_target=0.99, latency_p95_seconds=1, window_seconds=60)

    manager.record(category="success", success=True, latency_seconds=0.1)
    manager.record(category="business_deny", success=False, latency_seconds=0.1)
    assert manager.snapshot().status == "HEALTHY"

    manager.record(category="timeout", success=False, latency_seconds=2)
    snapshot = manager.snapshot()
    assert snapshot.status == "VIOLATED"
    assert snapshot.total_events == 2
