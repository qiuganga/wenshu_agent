import json

import pytest

from app.api.schemas.query_schema import QueryRequest
from app.core.exceptions import AgentNonRetryableError, AgentRetryExceededError
from app.service.query_service import QueryService


def make_service(graph):
    return QueryService(None, None, None, None, None, None, agent_graph=graph)


async def collect_events(service):
    return [event async for event in service.query(QueryRequest(query="hello"), None)]


def parse_sse_events(chunks):
    events = []
    for chunk in chunks:
        for block in chunk.strip().split("\n\n"):
            data_lines = [line.removeprefix("data: ") for line in block.splitlines() if line.startswith("data: ")]
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
    return events


def event_names(events):
    return [event["event"] for event in events]


def assert_no_final(events):
    assert "final" not in event_names(events)
    assert all("final_answer" not in json.dumps(event, ensure_ascii=False) for event in events)


class FailedGraph:
    def __init__(self, exc):
        self.exc = exc

    async def astream(self, **kwargs):
        yield {
            "event": "error",
            "node": "failed",
            "message": "safe failure",
            "code": "SQL_COST_TOO_HIGH",
            "retryable": True,
        }
        raise self.exc


class UnknownErrorGraph:
    async def astream(self, **kwargs):
        raise RuntimeError("password=secret host=127.0.0.1")
        yield  # pragma: no cover


class FinalGraph:
    async def astream(self, **kwargs):
        yield {
            "event": "result",
            "node": "interpret_result",
            "message": "Result interpreted",
            "final_answer": "fallback answer",
            "result_summary": {"row_count": 1},
        }


@pytest.mark.asyncio
async def test_query_service_does_not_duplicate_retry_exceeded_error_event():
    exc = AgentRetryExceededError(
        "safe failure",
        {"error_code": "SQL_COST_TOO_HIGH", "retryable": True, "error_already_emitted": True},
    )
    chunks = await collect_events(make_service(FailedGraph(exc)))
    events = parse_sse_events(chunks)
    errors = [event for event in events if event["event"] == "error"]
    done = [event for event in events if event["event"] == "done"]
    joined = json.dumps(events, ensure_ascii=False)

    assert event_names(events) == ["started", "error", "done"]
    assert len(errors) == 1
    assert len(done) == 1
    assert event_names(events).index("error") < event_names(events).index("done")
    assert_no_final(events)
    assert "validation_detail" not in joined
    assert "traceback" not in joined.lower()
    assert "password" not in joined.lower()
    assert "127.0.0.1" not in joined


@pytest.mark.asyncio
async def test_query_service_does_not_duplicate_non_retryable_error_event():
    exc = AgentNonRetryableError(
        "safe failure",
        {"error_code": "PERMISSION_DENIED", "retryable": False, "error_already_emitted": True},
    )
    chunks = await collect_events(make_service(FailedGraph(exc)))
    events = parse_sse_events(chunks)
    errors = [event for event in events if event["event"] == "error"]
    done = [event for event in events if event["event"] == "done"]
    joined = json.dumps(events, ensure_ascii=False)

    assert event_names(events) == ["started", "error", "done"]
    assert len(errors) == 1
    assert len(done) == 1
    assert_no_final(events)
    assert "validation_detail" not in joined


@pytest.mark.asyncio
async def test_query_service_unknown_exception_still_emits_one_sanitized_error_and_done():
    chunks = await collect_events(make_service(UnknownErrorGraph()))
    events = parse_sse_events(chunks)
    errors = [event for event in events if event["event"] == "error"]
    done = [event for event in events if event["event"] == "done"]
    joined = json.dumps(events, ensure_ascii=False)

    assert event_names(events) == ["started", "error", "done"]
    assert len(errors) == 1
    assert len(done) == 1
    assert "INTERNAL_ERROR" in joined
    assert event_names(events).index("error") < event_names(events).index("done")
    assert "password=secret" not in joined
    assert "127.0.0.1" not in joined
    assert_no_final(events)


@pytest.mark.asyncio
async def test_query_service_final_result_order_has_no_error():
    chunks = await collect_events(make_service(FinalGraph()))
    events = parse_sse_events(chunks)
    results = [event for event in events if event["event"] == "result"]
    done = [event for event in events if event["event"] == "done"]

    assert event_names(events) == ["started", "result", "done"]
    assert len(results) == 1
    assert len(done) == 1
    assert results[0]["data"]["final_answer"] == "fallback answer"
    assert event_names(events).index("result") < event_names(events).index("done")
    assert "error" not in event_names(events)
