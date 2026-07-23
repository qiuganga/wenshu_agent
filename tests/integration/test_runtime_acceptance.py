import asyncio
import json

import pytest
from starlette.testclient import TestClient

import main
from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QueryRequest
from app.service import query_service as query_service_module
from app.service.query_lifecycle import QueryAdmissionController, RequestDedupRegistry
from app.service.query_service import QueryService


class FakeRuntimeQueryService:
    async def query(self, query_request, request=None):
        yield 'event: started\ndata: {"event":"started","request_id":"rid","data":{"query_length":5}}\n\n'
        yield 'event: stage\ndata: {"event":"stage","node":"fake","message":"running"}\n\n'
        yield (
            'event: result\ndata: {"event":"result","node":"interpret_result",'
            '"data":{"final_answer":"ok","result_summary":{"row_count":1}}}\n\n'
        )
        yield 'event: done\ndata: {"event":"done","status":"ok"}\n\n'


class RecordingGraph:
    def __init__(self, *, delay: float = 0, fail: BaseException | None = None):
        self.delay = delay
        self.fail = fail
        self.calls = 0
        self.cancelled = False
        self.closed = False
        self.states = []

    async def astream(self, **kwargs):
        self.calls += 1
        self.states.append(kwargs["input"])
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail is not None:
                raise self.fail
            yield {"event": "stage", "node": "runtime", "message": "progress"}
            yield {
                "event": "result",
                "node": "interpret_result",
                "message": "Result interpreted",
                "final_answer": "accepted",
                "result_summary": {"row_count": 1},
            }
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.closed = True


class DisconnectRequest:
    def __init__(self, disconnected_after: int = 1):
        self.calls = 0
        self.disconnected_after = disconnected_after

    async def is_disconnected(self):
        self.calls += 1
        return self.calls >= self.disconnected_after


def fresh_service(monkeypatch, graph, *, max_global=20, max_per_user=3, admission_timeout=0.02):
    controller = QueryAdmissionController(
        max_global=max_global,
        max_per_user=max_per_user,
        timeout_seconds=admission_timeout,
    )
    registry = RequestDedupRegistry(ttl_seconds=30, max_entries=1000)
    monkeypatch.setattr(query_service_module, "admission_controller", controller)
    monkeypatch.setattr(query_service_module, "request_dedup_registry", registry)
    service = QueryService(None, None, None, None, None, None, agent_graph=graph)
    return service, controller, registry


async def collect(service, request, disconnect_request=None):
    return [chunk async for chunk in service.query(request, disconnect_request)]


def parse_sse(chunks):
    events = []
    for chunk in chunks:
        for block in chunk.strip().split("\n\n"):
            data_lines = [line.removeprefix("data: ") for line in block.splitlines() if line.startswith("data: ")]
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
    return events


def names(events):
    return [event["event"] for event in events]


def joined(events):
    return json.dumps(events, ensure_ascii=False)


def test_fastapi_runtime_smoke_openapi_and_query_route():
    async def override_service():
        return FakeRuntimeQueryService()

    main.app.dependency_overrides[get_query_service] = override_service
    try:
        with TestClient(main.app) as client:
            health = client.get("/health/live")
            openapi = client.get("/openapi.json")
            response = client.post("/api/v1/query", json={"query": "hello", "request_id": "runtime-1"})

        assert health.status_code == 200
        assert "/api/v1/query" in openapi.json()["paths"]
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse([response.text])
        assert names(events) == ["started", "stage", "result", "done"]
        assert events[2]["data"]["final_answer"] == "ok"
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_runtime_query_success_sse_order_and_single_graph_execution(monkeypatch):
    graph = RecordingGraph()
    service, controller, _registry = fresh_service(monkeypatch, graph)

    events = parse_sse(await collect(service, QueryRequest(query="hello", request_id="success-1")))

    assert names(events) == ["started", "stage", "result", "done"]
    assert graph.calls == 1
    assert events[2]["data"]["final_answer"] == "accepted"
    assert names(events).count("error") == 0
    assert names(events).count("result") == 1
    assert controller.snapshot_for("anonymous").global_active_queries == 0


@pytest.mark.asyncio
async def test_runtime_duplicate_request_rejected_without_graph_execution(monkeypatch):
    graph = RecordingGraph()
    service, _controller, _registry = fresh_service(monkeypatch, graph)
    request = QueryRequest(query="hello", request_id="dup-1")

    first = parse_sse(await collect(service, request))
    second = parse_sse(await collect(service, request))

    assert names(first) == ["started", "stage", "result", "done"]
    assert names(second) == ["started", "error", "done"]
    assert "DUPLICATE_REQUEST" in joined(second)
    assert graph.calls == 1


@pytest.mark.asyncio
async def test_runtime_global_and_user_admission_limits_recover_slots(monkeypatch):
    global_graph = RecordingGraph(delay=0.2)
    service, controller, _registry = fresh_service(monkeypatch, global_graph, max_global=1, max_per_user=2)

    first_task = asyncio.create_task(collect(service, QueryRequest(query="hello", request_id="limit-1", user_id="u1")))
    await asyncio.sleep(0.01)
    global_rejected = parse_sse(await collect(service, QueryRequest(query="hello", request_id="limit-2", user_id="u2")))
    first = parse_sse(await first_task)

    assert names(first) == ["started", "stage", "result", "done"]
    assert "QUERY_CONCURRENCY_LIMIT" in joined(global_rejected)
    assert controller.snapshot_for("u1").global_active_queries == 0

    user_graph = RecordingGraph(delay=0.2)
    service, controller, _registry = fresh_service(monkeypatch, user_graph, max_global=2, max_per_user=1)

    first_task = asyncio.create_task(collect(service, QueryRequest(query="hello", request_id="limit-3", user_id="u1")))
    await asyncio.sleep(0.01)
    user_rejected = parse_sse(await collect(service, QueryRequest(query="hello", request_id="limit-4", user_id="u1")))
    first = parse_sse(await first_task)

    assert names(first) == ["started", "stage", "result", "done"]
    assert "USER_QUERY_CONCURRENCY_LIMIT" in joined(user_rejected)
    assert controller.snapshot_for("u1").global_active_queries == 0
    assert controller.snapshot_for("u1").user_active_queries == 0


@pytest.mark.asyncio
async def test_runtime_total_timeout_cancels_graph_and_has_single_error(monkeypatch):
    monkeypatch.setattr(query_service_module.app_config.agent, "query_total_timeout_seconds", 0.01)
    graph = RecordingGraph(delay=0.2)
    service, controller, _registry = fresh_service(monkeypatch, graph)

    events = parse_sse(await collect(service, QueryRequest(query="hello", request_id="timeout-1")))

    assert names(events) == ["started", "error", "done"]
    assert names(events).count("error") == 1
    assert "QUERY_TOTAL_TIMEOUT" in joined(events)
    assert graph.cancelled is True
    assert controller.snapshot_for("anonymous").global_active_queries == 0


@pytest.mark.asyncio
async def test_runtime_disconnect_cleans_graph_admission_and_dedup(monkeypatch):
    graph = RecordingGraph(delay=1)
    service, controller, registry = fresh_service(monkeypatch, graph)

    events = parse_sse(
        await collect(service, QueryRequest(query="hello", request_id="disconnect-1"), DisconnectRequest())
    )

    assert names(events) == ["started"]
    assert graph.cancelled is True
    assert graph.closed is True
    assert controller.snapshot_for("anonymous").global_active_queries == 0
    token_hash = registry.hash_request_id("disconnect-1")
    assert registry._entries[token_hash].status == "cancelled"


@pytest.mark.asyncio
async def test_runtime_shutdown_rejects_new_request_and_clears_dedup(monkeypatch):
    graph = RecordingGraph(delay=1)
    service, controller, registry = fresh_service(monkeypatch, graph)
    token = await registry.register("shutdown-existing")

    await controller.begin_shutdown(timeout_seconds=0.01)
    await registry.clear()
    events = parse_sse(await collect(service, QueryRequest(query="hello", request_id="shutdown-1")))

    assert token.request_id_hash not in registry._entries
    assert names(events) == ["started", "error", "done"]
    assert "SERVICE_SHUTTING_DOWN" in joined(events)
    assert graph.calls == 0
