from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.agent.context import DataAgentContext
from app.agent.error_policy import classify_retryable_error
from app.agent.nodes.add_extra_context import add_extra_context
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.evaluate_sql_cost import evaluate_sql_cost
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.failed import failed
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.interpret_result import interpret_result
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.plan_query import plan_query
from app.agent.nodes.recall_column import recall_column
from app.agent.nodes.recall_metric import recall_metric
from app.agent.nodes.recall_value import recall_value
from app.agent.nodes.security_validate_sql import security_validate_sql
from app.agent.nodes.summarize_result import summarize_result
from app.agent.nodes.validate_sql import validate_sql
from app.agent.state import DataAgentState

NodeCallable = Callable[..., Any]


@dataclass(frozen=True)
class AgentNodes:
    extract_keywords: NodeCallable
    recall_column: NodeCallable
    recall_value: NodeCallable
    recall_metric: NodeCallable
    merge_retrieved_info: NodeCallable
    filter_table: NodeCallable
    filter_metric: NodeCallable
    add_extra_context: NodeCallable
    plan_query: NodeCallable
    generate_sql: NodeCallable
    security_validate_sql: NodeCallable
    database_validate_sql: NodeCallable
    evaluate_sql_cost: NodeCallable
    correct_sql: NodeCallable
    execute_sql: NodeCallable
    summarize_result: NodeCallable
    interpret_result: NodeCallable
    failed: NodeCallable


def default_agent_nodes() -> AgentNodes:
    return AgentNodes(
        extract_keywords=extract_keywords,
        recall_column=recall_column,
        recall_value=recall_value,
        recall_metric=recall_metric,
        merge_retrieved_info=merge_retrieved_info,
        filter_table=filter_table,
        filter_metric=filter_metric,
        add_extra_context=add_extra_context,
        plan_query=plan_query,
        generate_sql=generate_sql,
        security_validate_sql=security_validate_sql,
        database_validate_sql=validate_sql,
        evaluate_sql_cost=evaluate_sql_cost,
        correct_sql=correct_sql,
        execute_sql=execute_sql,
        summarize_result=summarize_result,
        interpret_result=interpret_result,
        failed=failed,
    )


def _route_after_validation_error(state: DataAgentState, success_node: str) -> str:
    if state.get("error") is None:
        return success_node

    retryable = state.get("retryable")
    if retryable is None:
        retryable = classify_retryable_error(
            state.get("error_code"),
            validation_detail=state.get("validation_detail"),
        )
    if not retryable:
        return "failed"
    if state.get("retry_count", 0) < state.get("max_retries", 2):
        return "correct_sql"
    return "failed"


def route_after_security_validation(state: DataAgentState) -> str:
    return _route_after_validation_error(state, "database_validate_sql")


def route_after_database_validation(state: DataAgentState) -> str:
    return _route_after_validation_error(state, "evaluate_sql_cost")


def route_after_cost_validation(state: DataAgentState) -> str:
    return _route_after_validation_error(state, "execute_sql")


def route_after_execution(state: DataAgentState) -> str:
    return _route_after_validation_error(state, "summarize_result")


def build_agent_graph(nodes: AgentNodes | None = None):
    active_nodes = nodes or default_agent_nodes()
    graph_builder = StateGraph(state_schema=DataAgentState, context_schema=DataAgentContext)

    graph_builder.add_node("extract_keywords", active_nodes.extract_keywords)
    graph_builder.add_node("recall_column", active_nodes.recall_column)
    graph_builder.add_node("recall_value", active_nodes.recall_value)
    graph_builder.add_node("recall_metric", active_nodes.recall_metric)
    graph_builder.add_node("merge_retrieved_info", active_nodes.merge_retrieved_info)
    graph_builder.add_node("filter_metric", active_nodes.filter_metric)
    graph_builder.add_node("filter_table", active_nodes.filter_table)
    graph_builder.add_node("add_extra_context", active_nodes.add_extra_context)
    graph_builder.add_node("plan_query", active_nodes.plan_query)
    graph_builder.add_node("generate_sql", active_nodes.generate_sql)
    graph_builder.add_node("security_validate_sql", active_nodes.security_validate_sql)
    graph_builder.add_node("database_validate_sql", active_nodes.database_validate_sql)
    graph_builder.add_node("evaluate_sql_cost", active_nodes.evaluate_sql_cost)
    graph_builder.add_node("correct_sql", active_nodes.correct_sql)
    graph_builder.add_node("execute_sql", active_nodes.execute_sql)
    graph_builder.add_node("summarize_result", active_nodes.summarize_result)
    graph_builder.add_node("interpret_result", active_nodes.interpret_result)
    graph_builder.add_node("failed", active_nodes.failed)

    graph_builder.add_edge(START, "extract_keywords")
    graph_builder.add_edge("extract_keywords", "recall_column")
    graph_builder.add_edge("extract_keywords", "recall_value")
    graph_builder.add_edge("extract_keywords", "recall_metric")
    graph_builder.add_edge("recall_column", "merge_retrieved_info")
    graph_builder.add_edge("recall_value", "merge_retrieved_info")
    graph_builder.add_edge("recall_metric", "merge_retrieved_info")
    graph_builder.add_edge("merge_retrieved_info", "filter_table")
    graph_builder.add_edge("merge_retrieved_info", "filter_metric")
    graph_builder.add_edge("filter_table", "add_extra_context")
    graph_builder.add_edge("filter_metric", "add_extra_context")
    graph_builder.add_edge("add_extra_context", "plan_query")
    graph_builder.add_edge("plan_query", "generate_sql")
    graph_builder.add_edge("generate_sql", "security_validate_sql")

    graph_builder.add_conditional_edges(
        "security_validate_sql",
        route_after_security_validation,
        {"database_validate_sql": "database_validate_sql", "correct_sql": "correct_sql", "failed": "failed"},
    )
    graph_builder.add_conditional_edges(
        "database_validate_sql",
        route_after_database_validation,
        {"evaluate_sql_cost": "evaluate_sql_cost", "correct_sql": "correct_sql", "failed": "failed"},
    )
    graph_builder.add_conditional_edges(
        "evaluate_sql_cost",
        route_after_cost_validation,
        {"execute_sql": "execute_sql", "correct_sql": "correct_sql", "failed": "failed"},
    )
    graph_builder.add_edge("correct_sql", "security_validate_sql")
    graph_builder.add_conditional_edges(
        "execute_sql",
        route_after_execution,
        {"summarize_result": "summarize_result", "correct_sql": "correct_sql", "failed": "failed"},
    )
    graph_builder.add_edge("summarize_result", "interpret_result")
    graph_builder.add_edge("interpret_result", END)
    graph_builder.add_edge("failed", END)
    return graph_builder.compile()


graph = build_agent_graph()
