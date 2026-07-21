from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from app.config.app_config import app_config
from app.models.es.value_info_es import ValueInfoES
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant


class ColumnInfoState(TypedDict, total=False):
    name: str
    type: str
    role: str
    examples: list[Any]
    description: str
    alias: list[str]


class TableInfoState(TypedDict, total=False):
    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class MetricInfoState(TypedDict, total=False):
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]


class DateInfoState(TypedDict, total=False):
    date: str
    weekday: str
    quarter: str


class DBInfoState(TypedDict, total=False):
    dialect: str
    version: str


class DataAgentState(TypedDict, total=False):
    query: str
    normalized_query: str
    keywords: list[str]
    retrieved_columns: list[ColumnInfoQdrant]
    retrieved_values: list[ValueInfoES]
    retrieved_metrics: list[MetricInfoQdrant]
    table_candidates: list[ColumnInfoQdrant]
    metric_candidates: list[MetricInfoQdrant]
    table_infos: list[TableInfoState]
    metric_infos: list[MetricInfoState]
    query_plan: dict[str, Any]
    date_info: DateInfoState
    db_info: DBInfoState
    sql: str
    normalized_sql: str
    sql_referenced_tables: list[str]
    sql_referenced_columns: dict[str, list[str]]
    error: str | None
    error_code: str | None
    validation_detail: str | None
    retryable: bool | None
    retry_count: int
    max_retries: int
    max_result_rows: int
    result: list[dict[str, Any]]
    result_row_count: int
    result_truncated: bool
    execution_time_ms: int
    sql_cost: dict[str, Any]
    result_summary: dict[str, Any]
    interpretation: str
    final_answer: str
    trace: list[dict[str, Any]]
    audit_logged: bool
    started_at: float
    budget: dict[str, float]
    budget_exhausted: bool
    admission_wait_ms: int
    global_active_queries: int
    user_active_queries: int
    dropped_sse_events: int
    duplicate_request: bool
    client_disconnected: bool
    visited_nodes: Annotated[list[str], operator.add]
    security_failures: int
    db_failures: int
    cost_failures: int


def create_initial_state(query: str, max_retries: int | None = None) -> DataAgentState:
    normalized_query = query.strip()
    return DataAgentState(
        query=normalized_query,
        normalized_query=normalized_query,
        keywords=[],
        retrieved_columns=[],
        retrieved_values=[],
        retrieved_metrics=[],
        table_candidates=[],
        metric_candidates=[],
        table_infos=[],
        metric_infos=[],
        query_plan={},
        date_info={},
        db_info={},
        sql="",
        normalized_sql="",
        sql_referenced_tables=[],
        sql_referenced_columns={},
        error=None,
        error_code=None,
        validation_detail=None,
        retryable=None,
        retry_count=0,
        max_retries=max_retries if max_retries is not None else app_config.agent.max_sql_retries,
        max_result_rows=app_config.agent.max_result_rows,
        result=[],
        result_row_count=0,
        result_truncated=False,
        execution_time_ms=0,
        sql_cost={},
        result_summary={},
        interpretation="",
        final_answer="",
        trace=[],
        audit_logged=False,
        started_at=time.monotonic(),
        budget={},
        budget_exhausted=False,
        admission_wait_ms=0,
        global_active_queries=0,
        user_active_queries=0,
        dropped_sse_events=0,
        duplicate_request=False,
        client_disconnected=False,
        visited_nodes=[],
        security_failures=0,
        db_failures=0,
        cost_failures=0,
    )
