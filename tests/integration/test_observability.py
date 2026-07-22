import json

import pytest

from app.api.schemas.query_schema import QueryRequest
from app.core.telemetry import telemetry_manager
from app.service import query_service as query_service_module
from app.service.query_lifecycle import QueryAdmissionController, RequestDedupRegistry
from app.service.query_service import QueryService


class FinalGraph:
    async def astream(self, **kwargs):
        yield {"event": "result", "message": "done", "final_answer": "ok"}


class FailingGraph:
    async def astream(self, **kwargs):
        raise RuntimeError("boom with password=secret")
        yield  # pragma: no cover


def service_for(graph):
    return QueryService(None, None, None, None, None, None, agent_graph=graph)


async def collect(service, request):
    return [chunk async for chunk in service.query(request, None)]


def parse_sse(chunks):
    events = []
    for chunk in chunks:
        data = [line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


@pytest.fixture(autouse=True)
def lifecycle(monkeypatch):
    monkeypatch.setattr(
        query_service_module,
        "request_dedup_registry",
        RequestDedupRegistry(ttl_seconds=30, max_entries=10),
    )
    monkeypatch.setattr(
        query_service_module,
        "admission_controller",
        QueryAdmissionController(max_global=2, max_per_user=2, timeout_seconds=0.01),
    )
    telemetry_manager.enable_test_capture()
    yield
    telemetry_manager.disable_test_capture()


@pytest.mark.asyncio
async def test_successful_query_records_trace_and_metrics():
    chunks = await collect(
        service_for(FinalGraph()),
        QueryRequest(query="hello", request_id="rid-1", execution_id="exec-1"),
    )
    events = parse_sse(chunks)

    assert [event["event"] for event in events] == ["started", "result", "done"]
    span_names = [span.name for span in telemetry_manager.captured_spans]
    assert "query_execution" in span_names
    assert "graph_execution" in span_names
    assert "redis.dedup" in span_names
    assert "redis.admission" in span_names
    assert any(metric.name == "query_success_total" for metric in telemetry_manager.captured_metrics)
    assert "secret" not in str(telemetry_manager.captured_spans)


@pytest.mark.asyncio
async def test_failed_query_records_error_span_without_sensitive_details():
    chunks = await collect(
        service_for(FailingGraph()),
        QueryRequest(query="hello", request_id="rid-2", execution_id="exec-2"),
    )
    events = parse_sse(chunks)

    assert [event["event"] for event in events] == ["started", "error", "done"]
    graph_spans = [span for span in telemetry_manager.captured_spans if span.name == "graph_execution"]
    assert graph_spans[-1].status == "error"
    assert any(metric.name == "query_failed_total" for metric in telemetry_manager.captured_metrics)
    assert "password=secret" not in str(telemetry_manager.captured_spans)
