import asyncio
import json
import time

import pytest

from app.agent.graph import _with_budget_guard
from app.api.schemas.query_schema import QueryRequest
from app.service import query_service as query_service_module
from app.service.query_lifecycle import (
    LifecycleSSEQueue,
    QueryAdmissionController,
    QueryExecutionBudget,
    QueryLifecycleError,
    RequestDedupRegistry,
)
from app.service.query_service import QueryService


class NeverGraph:
    def __init__(self):
        self.started = False

    async def astream(self, **kwargs):
        self.started = True
        yield {"event": "result", "message": "done", "final_answer": "ok"}


def service_for(graph):
    return QueryService(None, None, None, None, None, None, agent_graph=graph)


def parse_sse(chunks):
    events = []
    for chunk in chunks:
        data = [line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


@pytest.mark.asyncio
async def test_admission_global_limit_releases_and_cleans_user_count():
    controller = QueryAdmissionController(max_global=1, max_per_user=1, timeout_seconds=0.01)
    lease = await controller.acquire(user_id="u1", key="k1")

    with pytest.raises(QueryLifecycleError) as exc_info:
        await controller.acquire(user_id="u2", key="k2")

    assert exc_info.value.details["error_code"] == "QUERY_CONCURRENCY_LIMIT"
    await controller.release(lease)
    assert controller.snapshot_for("u1").global_active_queries == 0
    assert controller.snapshot_for("u1").user_active_queries == 0


@pytest.mark.asyncio
async def test_admission_user_limit_does_not_block_other_users():
    controller = QueryAdmissionController(max_global=2, max_per_user=1, timeout_seconds=0.01)
    first = await controller.acquire(user_id="u1", key="k1")
    second = await controller.acquire(user_id="u2", key="k2")

    with pytest.raises(QueryLifecycleError) as exc_info:
        await controller.acquire(user_id="u1", key="k3")

    assert exc_info.value.details["error_code"] == "USER_QUERY_CONCURRENCY_LIMIT"
    await controller.release(first)
    await controller.release(second)


@pytest.mark.asyncio
async def test_admission_cancelled_waiter_does_not_leak_slot():
    controller = QueryAdmissionController(max_global=1, max_per_user=1, timeout_seconds=1)
    lease = await controller.acquire(user_id="u1", key="k1")
    waiter = asyncio.create_task(controller.acquire(user_id="u2", key="k2"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await controller.release(lease)
    assert controller.snapshot_for("u2").global_active_queries == 0


@pytest.mark.asyncio
async def test_dedup_registry_ttl_status_and_eviction():
    registry = RequestDedupRegistry(ttl_seconds=0.02, max_entries=2)
    first = await registry.register("rid-1")
    assert len(first.request_id_hash) == 64
    with pytest.raises(QueryLifecycleError):
        await registry.register("rid-1")
    await registry.complete(first, "completed")
    await asyncio.sleep(0.03)
    await registry.register("rid-1")
    await registry.register("rid-2")
    await registry.register("rid-3")
    assert len(registry._entries) == 2
    assert "rid-1" not in str(registry._entries)


@pytest.mark.asyncio
async def test_query_service_duplicate_request_does_not_start_graph(monkeypatch):
    registry = RequestDedupRegistry(ttl_seconds=30, max_entries=10)
    controller = QueryAdmissionController(max_global=1, max_per_user=1, timeout_seconds=0.01)
    monkeypatch.setattr(query_service_module, "request_dedup_registry", registry)
    monkeypatch.setattr(query_service_module, "admission_controller", controller)
    graph = NeverGraph()
    service = service_for(graph)
    request = QueryRequest(query="hello", request_id="same")

    first_events = [event async for event in service.query(request, None)]
    second_events = [event async for event in service.query(request, None)]

    assert graph.started is True
    parsed = parse_sse(second_events)
    assert [event["event"] for event in parsed] == ["started", "error", "done"]
    assert "DUPLICATE_REQUEST" in json.dumps(parsed)
    assert sum("event: result" in event for event in first_events) == 1


@pytest.mark.asyncio
async def test_query_service_shutdown_rejects_before_graph(monkeypatch):
    registry = RequestDedupRegistry(ttl_seconds=30, max_entries=10)
    controller = QueryAdmissionController(max_global=1, max_per_user=1, timeout_seconds=0.01)
    await controller.begin_shutdown(timeout_seconds=0.01)
    monkeypatch.setattr(query_service_module, "request_dedup_registry", registry)
    monkeypatch.setattr(query_service_module, "admission_controller", controller)
    graph = NeverGraph()

    events = [event async for event in service_for(graph).query(QueryRequest(query="hello", request_id="rid"), None)]

    assert graph.started is False
    assert "SERVICE_SHUTTING_DOWN" in json.dumps(parse_sse(events))


def test_budget_uses_monotonic_deadline_and_local_timeout():
    budget = QueryExecutionBudget(total_timeout_seconds=10, started_at=time.monotonic())
    assert 0 < budget.local_timeout(30) <= 10
    expired = QueryExecutionBudget(total_timeout_seconds=0.001, started_at=time.monotonic() - 1)
    with pytest.raises(QueryLifecycleError):
        expired.remaining_or_raise()


@pytest.mark.asyncio
async def test_graph_budget_exhaustion_stops_before_next_node():
    calls = []

    async def node(state, runtime=None):
        calls.append("node")
        return {}

    guarded = _with_budget_guard(node)
    with pytest.raises(QueryLifecycleError):
        await guarded({"budget": {"deadline": time.monotonic() - 1, "started_at": time.monotonic() - 2}})
    assert calls == []


@pytest.mark.asyncio
async def test_sse_queue_drops_progress_but_keeps_one_final_and_error():
    stream = LifecycleSSEQueue(maxsize=1, put_timeout_seconds=0.01)
    await stream.put_graph_event({"event": "stage", "node": "n", "message": "one"})
    await stream.put_graph_event({"event": "stage", "node": "n", "message": "two"})
    assert stream.dropped_events == 1
    item = await stream.queue.get()
    assert item["message"] == "one"
    await stream.put_graph_event({"event": "result", "final_answer": "ok"})
    await stream.put_graph_event({"event": "result", "final_answer": "duplicate"})
    assert (await stream.queue.get())["final_answer"] == "ok"


@pytest.mark.asyncio
async def test_sse_queue_closed_raises_stream_closed():
    stream = LifecycleSSEQueue(maxsize=1, put_timeout_seconds=0.01)
    stream.closed = True
    with pytest.raises(QueryLifecycleError) as exc_info:
        await stream.put_graph_event({"event": "error", "message": "bad"})
    assert exc_info.value.code == "SSE_STREAM_CLOSED"
