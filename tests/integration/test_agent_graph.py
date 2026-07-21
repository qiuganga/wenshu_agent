import asyncio

import pytest
from langgraph.errors import NodeCancelledError

from app.agent.graph import AgentNodes, build_agent_graph, graph


def append_node(state: dict, name: str) -> list[str]:
    return [name]


def node(name: str, **extra):
    async def _node(state: dict, runtime):
        return {"visited_nodes": append_node(state, name), **extra}

    return _node


def validation_node(name: str, failure_key: str, error_code: str):
    async def _node(state: dict, runtime):
        visited = append_node(state, name)
        failures = state.get(failure_key, 0)
        if failures > 0:
            return {
                "visited_nodes": visited,
                failure_key: failures - 1,
                "error": f"{name} failed",
                "error_code": error_code,
                "retryable": True,
            }
        return {"visited_nodes": visited, "error": None, "error_code": None, "retryable": None}

    return _node


def correct_node():
    async def _node(state: dict, runtime):
        return {
            "visited_nodes": append_node(state, "correct_sql"),
            "retry_count": state.get("retry_count", 0) + 1,
            "error": None,
            "error_code": None,
            "retryable": None,
        }

    return _node


def execute_node(cancel: bool = False, fail: bool = False):
    async def _node(state: dict, runtime):
        if cancel:
            raise asyncio.CancelledError
        if fail:
            return {
                "visited_nodes": append_node(state, "execute_sql"),
                "error": "SQL execution timed out",
                "error_code": "QUERY_EXECUTION_TIMEOUT",
                "retryable": False,
            }
        return {"visited_nodes": append_node(state, "execute_sql")}

    return _node


def fake_nodes(cancel_at_execute: bool = False, fail_at_execute: bool = False) -> AgentNodes:
    return AgentNodes(
        extract_keywords=node("extract_keywords"),
        recall_column=node("recall_column"),
        recall_value=node("recall_value"),
        recall_metric=node("recall_metric"),
        merge_retrieved_info=node("merge_retrieved_info"),
        filter_table=node("filter_table"),
        filter_metric=node("filter_metric"),
        add_extra_context=node("add_extra_context"),
        plan_query=node("plan_query"),
        generate_sql=node("generate_sql", error=None),
        security_validate_sql=validation_node("security_validate_sql", "security_failures", "SQL_SECURITY_FAILED"),
        database_validate_sql=validation_node("database_validate_sql", "db_failures", "SQL_VALIDATION_FAILED"),
        evaluate_sql_cost=validation_node("evaluate_sql_cost", "cost_failures", "SQL_COST_TOO_HIGH"),
        correct_sql=correct_node(),
        execute_sql=execute_node(cancel_at_execute, fail_at_execute),
        summarize_result=node("summarize_result"),
        interpret_result=node("interpret_result"),
        failed=node("failed"),
    )


async def run_graph(input_state: dict, cancel_at_execute: bool = False, fail_at_execute: bool = False) -> dict:
    compiled = build_agent_graph(fake_nodes(cancel_at_execute, fail_at_execute))
    return await compiled.ainvoke(input_state)


@pytest.mark.asyncio
async def test_graph_success_full_path():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "visited_nodes": []})
    visited = state["visited_nodes"]
    assert visited[0] == "extract_keywords"
    assert {"recall_column", "recall_value", "recall_metric"}.issubset(visited)
    assert visited.index("merge_retrieved_info") > max(
        visited.index("recall_column"),
        visited.index("recall_value"),
        visited.index("recall_metric"),
    )
    assert {"filter_table", "filter_metric"}.issubset(visited)
    assert visited.index("add_extra_context") > max(visited.index("filter_table"), visited.index("filter_metric"))
    assert (
        visited[-7:]
        == [
            "plan_query",
            "generate_sql",
            "security_validate_sql",
            "database_validate_sql",
            "evaluate_sql_cost",
            "execute_sql",
            "summarize_result",
            "interpret_result",
        ][-7:]
    )


@pytest.mark.asyncio
async def test_security_validation_fail_then_correct_then_success():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "security_failures": 1, "visited_nodes": []})
    assert "correct_sql" in state["visited_nodes"]
    assert state["visited_nodes"].count("security_validate_sql") == 2
    assert state["visited_nodes"][-3:] == ["execute_sql", "summarize_result", "interpret_result"]


@pytest.mark.asyncio
async def test_database_validation_fail_then_correct_then_success():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "db_failures": 1, "visited_nodes": []})
    assert state["visited_nodes"].count("database_validate_sql") == 2
    assert "correct_sql" in state["visited_nodes"]


@pytest.mark.asyncio
async def test_cost_validation_fail_then_correct_then_success():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "cost_failures": 1, "visited_nodes": []})
    assert state["visited_nodes"].count("evaluate_sql_cost") == 2
    assert "correct_sql" in state["visited_nodes"]


@pytest.mark.asyncio
async def test_retry_exceeded_routes_failed_and_does_not_execute_sql():
    state = await run_graph({"retry_count": 2, "max_retries": 2, "security_failures": 1, "visited_nodes": []})
    assert "failed" in state["visited_nodes"]
    assert "execute_sql" not in state["visited_nodes"]


@pytest.mark.asyncio
async def test_cancellation_stops_later_nodes():
    with pytest.raises(NodeCancelledError):
        await run_graph({"retry_count": 0, "max_retries": 2, "visited_nodes": []}, cancel_at_execute=True)


@pytest.mark.asyncio
async def test_execute_failure_routes_to_failed_without_summarize_result():
    state = await run_graph({"retry_count": 0, "max_retries": 2, "visited_nodes": []}, fail_at_execute=True)

    assert "failed" in state["visited_nodes"]
    assert "summarize_result" not in state["visited_nodes"]
    assert "interpret_result" not in state["visited_nodes"]


@pytest.mark.asyncio
async def test_guarded_nodes_receive_runtime_context():
    async def runtime_node(state: dict, runtime):
        return {"visited_nodes": append_node(state, f"extract_keywords:{runtime.context['value']}")}

    nodes = fake_nodes()
    compiled = build_agent_graph(nodes.__class__(**{**nodes.__dict__, "extract_keywords": runtime_node}))

    state = await compiled.ainvoke(
        {"retry_count": 0, "max_retries": 2, "visited_nodes": []},
        context={"value": "available"},
    )

    assert state["visited_nodes"][0] == "extract_keywords:available"


def test_production_graph_imports_and_compiles():
    assert graph is not None
    assert build_agent_graph() is not None
