from __future__ import annotations

import json

import pytest

from app.agent.checkpoint import CHECKPOINT_SAVE_LUA, CheckpointManager
from app.agent.graph import AgentNodes, build_agent_graph
from app.agent.state import create_initial_state
from app.api.schemas.query_schema import QueryRequest
from app.service import query_service as query_service_module
from app.service.query_lifecycle import QueryAdmissionController, RequestDedupRegistry
from app.service.query_service import QueryService


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def eval(self, script: str, numkeys: int, *args):
        assert script == CHECKPOINT_SAVE_LUA
        key = args[0]
        payload = str(args[1])
        existing = self.values.get(key)
        if existing is not None:
            old_status = json.loads(existing)["status"]
            new_status = json.loads(payload)["status"]
            if old_status == "COMPLETED" and new_status != "COMPLETED":
                return "invalid"
            if old_status in {"FAILED", "CANCELLED"} and new_status == "RUNNING":
                return "invalid"
        self.values[key] = payload
        return "ok"


def manager_for(redis: FakeRedis) -> CheckpointManager:
    return CheckpointManager(redis_client=lambda: redis, key_prefix="agent", ttl_seconds=60)


def parse_sse(chunks: list[str]) -> list[dict]:
    events = []
    for chunk in chunks:
        data = [line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


def event_names(events: list[dict]) -> list[str]:
    return [event["event"] for event in events]


def node(name: str, calls: dict[str, int]):
    async def _node(state: dict, runtime):
        calls[name] = calls.get(name, 0) + 1
        return {"visited_nodes": [name]}

    return _node


def validation_node(name: str, calls: dict[str, int]):
    async def _node(state: dict, runtime):
        calls[name] = calls.get(name, 0) + 1
        return {"visited_nodes": [name], "error": None, "error_code": None, "retryable": None}

    return _node


def fake_nodes(calls: dict[str, int]) -> AgentNodes:
    return AgentNodes(
        extract_keywords=node("extract_keywords", calls),
        recall_column=node("recall_column", calls),
        recall_value=node("recall_value", calls),
        recall_metric=node("recall_metric", calls),
        merge_retrieved_info=node("merge_retrieved_info", calls),
        filter_table=node("filter_table", calls),
        filter_metric=node("filter_metric", calls),
        add_extra_context=node("add_extra_context", calls),
        plan_query=node("plan_query", calls),
        generate_sql=node("generate_sql", calls),
        security_validate_sql=validation_node("security_validate_sql", calls),
        database_validate_sql=validation_node("database_validate_sql", calls),
        evaluate_sql_cost=validation_node("evaluate_sql_cost", calls),
        correct_sql=node("correct_sql", calls),
        execute_sql=node("execute_sql", calls),
        summarize_result=node("summarize_result", calls),
        interpret_result=node("interpret_result", calls),
        failed=node("failed", calls),
    )


@pytest.mark.asyncio
async def test_graph_recovery_skips_completed_node_and_resumes_next(monkeypatch):
    redis = FakeRedis()
    manager = manager_for(redis)
    monkeypatch.setattr("app.agent.graph.checkpoint_manager", manager)
    await manager.mark_node_completed(
        "exec-1",
        "req-1",
        "extract_keywords",
        "recall_column",
        {"execution_id": "exec-1", "request_id": "req-1", "retry_count": 0, "visited_nodes": ["extract_keywords"]},
        {"visited_nodes": ["extract_keywords"]},
    )
    await manager.mark_node_running(
        "exec-1",
        "req-1",
        "recall_column",
        {"execution_id": "exec-1", "request_id": "req-1", "retry_count": 0, "visited_nodes": ["extract_keywords"]},
    )
    calls: dict[str, int] = {}
    compiled = build_agent_graph(fake_nodes(calls))
    state = create_initial_state("hello")
    state["execution_id"] = "exec-1"
    state["request_id"] = "req-1"
    state = await manager.resume_state(state, "exec-1")  # type: ignore[assignment]

    result = await compiled.ainvoke(state)

    assert calls.get("extract_keywords", 0) == 0
    assert calls["recall_column"] == 1
    assert "interpret_result" in result["visited_nodes"]


class ResultGraph:
    async def astream(self, **kwargs):
        yield {"event": "result", "message": "done", "final_answer": "ok"}


def service_for(graph):
    return QueryService(None, None, None, None, None, None, agent_graph=graph)


@pytest.mark.asyncio
async def test_query_service_resume_does_not_emit_duplicate_started(monkeypatch):
    redis = FakeRedis()
    manager = manager_for(redis)
    monkeypatch.setattr(query_service_module, "checkpoint_manager", manager)
    monkeypatch.setattr(
        query_service_module,
        "request_dedup_registry",
        RequestDedupRegistry(ttl_seconds=30, max_entries=10),
    )
    monkeypatch.setattr(
        query_service_module,
        "admission_controller",
        QueryAdmissionController(max_global=1, max_per_user=1, timeout_seconds=0.01),
    )
    await manager.mark_started_emitted(
        "exec-1",
        "req-1",
        {"execution_id": "exec-1", "request_id": "req-1", "retry_count": 0},
    )

    chunks = [
        chunk
        async for chunk in service_for(ResultGraph()).query(QueryRequest(query="hello", execution_id="exec-1"), None)
    ]
    events = parse_sse(chunks)

    assert event_names(events) == ["result", "done"]
    assert events[0]["data"]["final_answer"] == "ok"
