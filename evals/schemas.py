from __future__ import annotations

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    question: str
    expected_tables: list[str] = Field(default_factory=list)
    expected_columns: list[str] = Field(default_factory=list)
    expected_metrics: list[str] = Field(default_factory=list)
    forbidden_tables: list[str] = Field(default_factory=list)
    expected_sql_contains: list[str] = Field(default_factory=list)
    expected_sql_not_contains: list[str] = Field(default_factory=list)
    expected_result: dict | list | None = None
    tags: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    case_count: int
    table_recall: float
    table_precision: float
    column_recall: float
    column_precision: float
    metric_accuracy: float
    sql_parse_success_rate: float
    sql_security_pass_rate: float
    sql_execution_success_rate: float
    result_accuracy: float
    correction_success_rate: float
    average_latency_ms: float
    average_retry_count: float
