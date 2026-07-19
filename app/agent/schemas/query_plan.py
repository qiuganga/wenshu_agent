from __future__ import annotations

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    intent: str = ""
    tables: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int | None = None
    assumptions: list[str] = Field(default_factory=list)


class SQLGenerationResult(BaseModel):
    sql: str = Field(min_length=1)


class TableSelectionResult(BaseModel):
    selected_tables: list[str] = Field(default_factory=list)


class MetricSelectionResult(BaseModel):
    selected_metrics: list[str] = Field(default_factory=list)
