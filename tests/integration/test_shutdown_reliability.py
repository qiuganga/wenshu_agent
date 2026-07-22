import pytest

from app.api.routers import health_router as health_module
from app.service.query_lifecycle import QueryAdmissionController, QueryLifecycleError


@pytest.mark.asyncio
async def test_shutdown_rejects_new_requests_with_service_shutting_down():
    controller = QueryAdmissionController(max_global=1, max_per_user=1, timeout_seconds=0.01)

    await controller.begin_shutdown(timeout_seconds=0.01)

    with pytest.raises(QueryLifecycleError) as exc:
        await controller.acquire(user_id="u1", key="k1")
    assert exc.value.code == "SERVICE_SHUTTING_DOWN"


@pytest.mark.asyncio
async def test_qdrant_unavailable_makes_ready_degraded(monkeypatch):
    async def ok():
        return True

    async def fail():
        return False

    monkeypatch.setattr(health_module, "_check_mysql", lambda manager: ok())
    monkeypatch.setattr(health_module, "_check_qdrant", fail)
    monkeypatch.setattr(health_module, "_check_es", ok)
    monkeypatch.setattr(health_module, "_check_redis", ok)
    monkeypatch.setattr(health_module, "_check_embedding", ok)

    result = await health_module.ready()

    assert result["status"] == "degraded"
    assert result["checks"]["qdrant"] is False


@pytest.mark.asyncio
async def test_mysql_unavailable_makes_ready_degraded(monkeypatch):
    async def ok():
        return True

    async def fail(manager):
        return False

    monkeypatch.setattr(health_module, "_check_mysql", fail)
    monkeypatch.setattr(health_module, "_check_qdrant", ok)
    monkeypatch.setattr(health_module, "_check_es", ok)
    monkeypatch.setattr(health_module, "_check_redis", ok)
    monkeypatch.setattr(health_module, "_check_embedding", ok)

    result = await health_module.ready()

    assert result["status"] == "degraded"
    assert result["checks"]["meta_mysql"] is False
    assert result["checks"]["dw_mysql"] is False
