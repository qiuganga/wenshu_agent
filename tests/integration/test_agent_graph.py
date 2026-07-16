import asyncio
from typing import Any, TypedDict

import pytest
from langgraph.constants import END, START
from langgraph.errors import NodeCancelledError
from langgraph.graph import StateGraph

from app.agent.graph import route_after_database_validation, route_after_security_validation


class GraphTestState(TypedDict, total=False):
    visited_nodes: list[str]
    error: str | None
    retry_count: int
    max_retries: int
    security_failures: int
    db_failures: int
    cancelled: bool


def append_node(state: GraphTestState, name: str) -> list[str]:
    return [*state.get("visited_nodes", []), name]


def build_test_graph(cancel_at_execute: bool = False):
    async def start_node(state: GraphTestState):
        return {"visited_nodes": append_node(state, "generate_sql"), "error": None}

    async def security_node(state: GraphTestState):
        visited = append_node(state, "security_validate_sql")
        failures = state.get("security_failures", 0)
        if failures > 0:
            return {"visited_nodes": visited, "security_failures": failures - 1, "error": "security failed"}
        return {"visited_nodes": visited, "error": None}

    async def db_node(state: GraphTestState):
        visited = append_node(state, "database_validate_sql")
        failures = state.get("db_failures", 0)
        if failures > 0:
            return {"visited_nodes": visited, "db_failures": failures - 1, "error": "db failed"}
        return {"visited_nodes": visited, "error": None}

    async def correct_node(state: GraphTestState):
        return {
            "visited_nodes": append_node(state, "correct_sql"),
            "retry_count": state.get("retry_count", 0) + 1,
            "error": None,
        }

    async def execute_node(state: GraphTestState):
        if cancel_at_execute:
            raise asyncio.CancelledError
        return {"visited_nodes": append_node(state, "execute_sql")}

    async def failed_node(state: GraphTestState):
        return {"visited_nodes": append_node(state, "failed")}

    builder = StateGraph(GraphTestState)
    builder.add_node("generate_sql", start_node)
    builder.add_node("security_validate_sql", security_node)
    builder.add_node("database_validate_sql", db_node)
    builder.add_node("correct_sql", correct_node)
    builder.add_node("execute_sql", execute_node)
    builder.add_node("failed", failed_node)
    builder.add_edge(START, "generate_sql")
    builder.add_edge("generate_sql", "security_validate_sql")
    builder.add_conditional_edges(
        "security_validate_sql",
        route_after_security_validation,
        {"database_validate_sql": "database_validate_sql", "correct_sql": "correct_sql", "failed": "failed"},
    )
    builder.add_conditional_edges(
        "database_validate_sql",
        route_after_database_validation,
        {"execute_sql": "execute_sql", "correct_sql": "correct_sql", "failed": "failed"},
    )
    builder.add_edge("correct_sql", "security_validate_sql")
    builder.add_edge("execute_sql", END)
    builder.add_edge("failed", END)
    return builder.compile()


async def run_graph(input_state: dict[str, Any]) -> GraphTestState:
    return await build_test_graph().ainvoke(input_state)


@pytest.mark.asyncio
async def test_graph_success_full_path():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "visited_nodes": []})
    assert state["visited_nodes"] == [
        "generate_sql",
        "security_validate_sql",
        "database_validate_sql",
        "execute_sql",
    ]


@pytest.mark.asyncio
async def test_security_validation_fail_then_correct_then_success():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "security_failures": 1, "visited_nodes": []})
    assert state["visited_nodes"] == [
        "generate_sql",
        "security_validate_sql",
        "correct_sql",
        "security_validate_sql",
        "database_validate_sql",
        "execute_sql",
    ]


@pytest.mark.asyncio
async def test_database_validation_fail_then_correct_then_success():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "db_failures": 1, "visited_nodes": []})
    assert state["visited_nodes"] == [
        "generate_sql",
        "security_validate_sql",
        "database_validate_sql",
        "correct_sql",
        "security_validate_sql",
        "database_validate_sql",
        "execute_sql",
    ]


@pytest.mark.asyncio
async def test_retry_exceeded_routes_failed():
    state = await run_graph({"retry_count": 2, "max_retries": 2, "security_failures": 1, "visited_nodes": []})
    assert state["visited_nodes"] == ["generate_sql", "security_validate_sql", "failed"]


@pytest.mark.asyncio
async def test_cancellation_stops_later_nodes():
    graph = build_test_graph(cancel_at_execute=True)
    with pytest.raises(NodeCancelledError):
        await graph.ainvoke({"retry_count": 0, "max_retries": 2, "visited_nodes": []})
