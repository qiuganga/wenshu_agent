from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.core.exceptions import SQLSecurityError

SYSTEM_SCHEMAS = {"mysql", "information_schema", "performance_schema", "sys"}
BANNED_SQL_FRAGMENTS = ("into outfile", "load data")


class SQLValidationResult(BaseModel):
    normalized_sql: str
    referenced_tables: list[str]
    has_limit: bool
    statement_type: str


class SQLGenerationResult(BaseModel):
    sql: str = Field(min_length=1)


class TableSelectionResult(BaseModel):
    tables: dict[str, list[str]] = Field(default_factory=dict)


class MetricSelectionResult(BaseModel):
    metric_ids: list[str] = Field(default_factory=list)


def _statement_type(expression: exp.Expression) -> str:
    if isinstance(expression, exp.Select | exp.Union | exp.Intersect | exp.Except):
        return "SELECT"
    return expression.key.upper()


def _is_readonly_select(expression: exp.Expression) -> bool:
    return isinstance(expression, exp.Select | exp.Union | exp.Intersect | exp.Except)


def _referenced_tables(expression: exp.Expression) -> list[str]:
    tables: set[str] = set()
    cte_aliases = {cte.alias.lower() for cte in expression.find_all(exp.CTE) if cte.alias}
    for table in expression.find_all(exp.Table):
        table_name = table.name
        db_name = table.db
        if not table_name or table_name.lower() in cte_aliases:
            continue
        if db_name:
            tables.add(f"{db_name}.{table_name}".lower())
        else:
            tables.add(table_name.lower())
    return sorted(tables)


def validate_readonly_sql(sql: str, allowed_tables: set[str], dialect: str = "mysql") -> SQLValidationResult:
    raw_sql = sql.strip()
    if not raw_sql:
        raise SQLSecurityError("SQL is empty")

    lowered = raw_sql.lower()
    if any(fragment in lowered for fragment in BANNED_SQL_FRAGMENTS):
        raise SQLSecurityError("SQL contains a banned clause")

    try:
        expressions = [expr for expr in parse(raw_sql, read=dialect) if expr is not None]
    except ParseError as exc:
        raise SQLSecurityError("SQL parse failed") from exc

    if len(expressions) != 1:
        raise SQLSecurityError("Only one SQL statement is allowed")

    expression = cast(exp.Expression, expressions[0])
    statement_type = _statement_type(expression)
    if not _is_readonly_select(expression):
        raise SQLSecurityError("Only SELECT or WITH ... SELECT statements are allowed")

    referenced_tables = _referenced_tables(expression)
    normalized_allowed = {table.lower() for table in allowed_tables}
    for table in referenced_tables:
        short_name = table.split(".")[-1]
        schema = table.split(".")[0] if "." in table else None
        if schema in SYSTEM_SCHEMAS or short_name in SYSTEM_SCHEMAS:
            raise SQLSecurityError("System schemas and system tables are not allowed")
        if table not in normalized_allowed and short_name not in normalized_allowed:
            raise SQLSecurityError(f"Table is not allowed: {table}")

    normalized_sql = expression.sql(dialect=dialect)
    return SQLValidationResult(
        normalized_sql=normalized_sql,
        referenced_tables=referenced_tables,
        has_limit=expression.args.get("limit") is not None,
        statement_type=statement_type,
    )


def ensure_select_limit(sql: str, max_rows: int, dialect: str = "mysql") -> str:
    expressions = [expr for expr in parse(sql.strip(), read=dialect) if expr is not None]
    if len(expressions) != 1:
        raise SQLSecurityError("Only one SQL statement is allowed")
    expression = cast(exp.Expression, expressions[0])
    if expression.args.get("limit") is None:
        expression = cast(Any, expression).limit(max_rows)
    return expression.sql(dialect=dialect)

