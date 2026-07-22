from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from app.evaluation.metrics import MetricResult, ratio_score


@dataclass(frozen=True)
class SQLEvaluationInput:
    actual_sql: str | None = None
    expected_sql: str | None = None
    expected_tables: list[str] = field(default_factory=list)
    expected_columns: dict[str, list[str]] = field(default_factory=dict)
    execution_success: bool = False
    result_match: bool | None = None


def evaluate_sql(value: SQLEvaluationInput) -> list[MetricResult]:
    actual_ast = _parse(value.actual_sql)
    expected_ast = _parse(value.expected_sql)
    actual_tables = _tables(actual_ast)
    expected_tables = set(_tables(expected_ast) or [table.lower() for table in value.expected_tables])
    actual_columns = _columns(actual_ast)
    expected_columns = _expected_columns(expected_ast, value.expected_columns)
    return [
        MetricResult("sql_execution_success", 1.0 if value.execution_success else 0.0),
        MetricResult("schema_accuracy", 1.0 if actual_ast is not None else 0.0),
        MetricResult("table_selection_accuracy", ratio_score(actual_tables, expected_tables)),
        MetricResult("column_accuracy", ratio_score(actual_columns, expected_columns)),
        MetricResult("result_match", 1.0 if value.result_match else 0.0 if value.result_match is False else 1.0),
    ]


def _parse(sql: str | None) -> exp.Expression | None:
    if not sql:
        return None
    try:
        expression = parse_one(sql, read="mysql")
    except ParseError:
        return None
    if not isinstance(expression, exp.Select | exp.Union | exp.Intersect | exp.Except):
        return None
    return expression


def _tables(expression: exp.Expression | None) -> set[str]:
    if expression is None:
        return set()
    return {table.name.lower() for table in expression.find_all(exp.Table) if table.name}


def _columns(expression: exp.Expression | None) -> set[str]:
    if expression is None:
        return set()
    return {column.name.lower() for column in expression.find_all(exp.Column) if column.name}


def _expected_columns(expression: exp.Expression | None, expected_columns: dict[str, list[str]]) -> set[str]:
    if expected_columns:
        return {column.lower() for columns in expected_columns.values() for column in columns}
    return _columns(expression)
