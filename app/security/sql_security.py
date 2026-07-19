from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.core.exceptions import SQLSecurityError

SYSTEM_SCHEMAS = {"mysql", "information_schema", "performance_schema", "sys"}
BANNED_SQL_CAPABILITY_PATTERNS = (
    re.compile(r"\binto\s+out\s*file\b", re.IGNORECASE),
    re.compile(r"\binto\s+dump\s*file\b", re.IGNORECASE),
    re.compile(r"\bload\s+data\b", re.IGNORECASE),
    re.compile(r"\bhandler\b", re.IGNORECASE),
    re.compile(r"\bprepare\b", re.IGNORECASE),
    re.compile(r"\bexecute\b", re.IGNORECASE),
    re.compile(r"\bdeallocate\s+prepare\b", re.IGNORECASE),
)
BANNED_FUNCTIONS = frozenset(
    {
        "sleep",
        "benchmark",
        "get_lock",
        "release_lock",
        "is_free_lock",
        "is_used_lock",
        "load_file",
        "master_pos_wait",
        "uuid_short",
    }
)


def _strip_literals_comments_and_quoted_identifiers(sql: str) -> str:
    result: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < length else ""
        if char in {"'", '"', "`"}:
            quote = char
            result.append(" ")
            index += 1
            while index < length:
                if sql[index] == "\\":
                    index += 2
                    continue
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote and quote in {"'", '"'}:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "-" and nxt == "-":
            result.append(" ")
            index += 2
            while index < length and sql[index] not in "\r\n":
                index += 1
            continue
        if char == "#":
            result.append(" ")
            index += 1
            while index < length and sql[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and nxt == "*":
            result.append(" ")
            index += 2
            while index + 1 < length and not (sql[index] == "*" and sql[index + 1] == "/"):
                index += 1
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


class SQLValidationResult(BaseModel):
    normalized_sql: str
    referenced_tables: list[str]
    referenced_columns: dict[str, list[str]] = Field(default_factory=dict)
    has_limit: bool
    statement_type: str


class SQLGenerationResult(BaseModel):
    sql: str = Field(min_length=1)


def _statement_type(expression: exp.Expression) -> str:
    if isinstance(expression, exp.Select | exp.Union | exp.Intersect | exp.Except):
        return "SELECT"
    return expression.key.upper()


def _is_readonly_select(expression: exp.Expression) -> bool:
    return isinstance(expression, exp.Select | exp.Union | exp.Intersect | exp.Except)


def _cte_aliases(expression: exp.Expression) -> set[str]:
    return {cte.alias.lower() for cte in expression.find_all(exp.CTE) if cte.alias}


def _table_name(table: exp.Table) -> str:
    if table.db:
        return f"{table.db}.{table.name}".lower()
    return table.name.lower()


def _referenced_tables(expression: exp.Expression) -> list[str]:
    tables: set[str] = set()
    cte_aliases = _cte_aliases(expression)
    for table in expression.find_all(exp.Table):
        table_name = table.name
        if not table_name or table_name.lower() in cte_aliases:
            continue
        tables.add(_table_name(table))
    return sorted(tables)


def _physical_table_aliases(expression: exp.Expression) -> dict[str, str]:
    aliases: dict[str, str] = {}
    cte_aliases = _cte_aliases(expression)
    for table in expression.find_all(exp.Table):
        if not table.name or table.name.lower() in cte_aliases:
            continue
        table_name = _table_name(table)
        aliases[table.name.lower()] = table_name
        aliases[table_name] = table_name
        if table.alias:
            aliases[table.alias.lower()] = table_name
    return aliases


def _output_aliases(expression: exp.Expression) -> set[str]:
    aliases: set[str] = set()
    for select in expression.find_all(exp.Select):
        for projection in select.expressions:
            alias = projection.alias
            if alias:
                aliases.add(alias.lower())
    return aliases


def _normalize_allowed_columns(allowed_columns: dict[str, set[str]] | None) -> dict[str, set[str]] | None:
    if allowed_columns is None:
        return None
    return {table.lower(): {column.lower() for column in columns} for table, columns in allowed_columns.items()}


def _allowed_column_set(table_name: str, allowed_columns: dict[str, set[str]] | None) -> set[str] | None:
    if allowed_columns is None:
        return None
    short_name = table_name.split(".")[-1]
    return allowed_columns.get(table_name) or allowed_columns.get(short_name)


def _assert_allowed_tables(referenced_tables: Iterable[str], allowed_tables: set[str]) -> None:
    normalized_allowed = {table.lower() for table in allowed_tables}
    for table in referenced_tables:
        short_name = table.split(".")[-1]
        schema = table.split(".")[0] if "." in table else None
        if schema in SYSTEM_SCHEMAS or short_name in SYSTEM_SCHEMAS:
            raise SQLSecurityError("System schemas and system tables are not allowed")
        if table not in normalized_allowed and short_name not in normalized_allowed:
            raise SQLSecurityError(f"Table is not allowed: {table}")


def _assert_no_banned_capabilities(
    raw_sql: str,
    expression: exp.Expression,
    banned_functions: set[str] | None = None,
) -> None:
    sanitized_sql = _strip_literals_comments_and_quoted_identifiers(raw_sql)
    if any(pattern.search(sanitized_sql) for pattern in BANNED_SQL_CAPABILITY_PATTERNS):
        raise SQLSecurityError("SQL contains a banned capability")

    active_banned_functions = BANNED_FUNCTIONS | {name.lower() for name in (banned_functions or set())}
    for func in expression.find_all(exp.Func):
        if isinstance(func, exp.Anonymous):
            name = str(func.this).lower()
        else:
            name = (func.sql_name() or func.key).lower()
        if name in active_banned_functions:
            raise SQLSecurityError(f"SQL function is not allowed: {name}")


def _assert_star_policy(expression: exp.Expression, allow_select_star: bool) -> None:
    if allow_select_star:
        return
    if any(True for _ in expression.find_all(exp.Star)):
        raise SQLSecurityError("SELECT * is not allowed")


def _collect_referenced_columns(
    expression: exp.Expression,
    referenced_tables: list[str],
    allowed_columns: dict[str, set[str]] | None,
) -> dict[str, set[str]]:
    if allowed_columns is None:
        return {}

    table_aliases = _physical_table_aliases(expression)
    output_aliases = _output_aliases(expression)
    cte_aliases = _cte_aliases(expression)
    referenced: dict[str, set[str]] = {table: set() for table in referenced_tables}

    for column in expression.find_all(exp.Column):
        column_name = column.name.lower()
        table_qualifier = (column.table or "").lower()
        if not column_name:
            continue
        if not table_qualifier and column_name in output_aliases:
            continue

        if table_qualifier:
            if table_qualifier in cte_aliases:
                continue
            physical_table = table_aliases.get(table_qualifier)
            if physical_table is None:
                raise SQLSecurityError(f"Unknown table or alias in column reference: {table_qualifier}")
            allowed = _allowed_column_set(physical_table, allowed_columns)
            if allowed is not None and column_name not in allowed:
                raise SQLSecurityError(f"Column is not allowed: {physical_table}.{column_name}")
            referenced.setdefault(physical_table, set()).add(column_name)
            continue

        scope = column.find_ancestor(exp.Select)
        scope_tables = _referenced_tables(scope) if scope is not None else referenced_tables
        if not scope_tables:
            scope_tables = referenced_tables
        candidate_tables = []
        for table in scope_tables:
            allowed = _allowed_column_set(table, allowed_columns)
            if allowed is not None and column_name in allowed:
                candidate_tables.append(table)
        if len(candidate_tables) == 1:
            referenced.setdefault(candidate_tables[0], set()).add(column_name)
        elif len(candidate_tables) == 0:
            raise SQLSecurityError(f"Column is not allowed: {column_name}")
        else:
            raise SQLSecurityError(f"Ambiguous unqualified column reference: {column_name}")

    return referenced


def _parse_single(sql: str, dialect: str) -> exp.Expression:
    try:
        expressions = [expr for expr in parse(sql.strip(), read=dialect) if expr is not None]
    except ParseError as exc:
        raise SQLSecurityError("SQL parse failed") from exc
    if len(expressions) != 1:
        raise SQLSecurityError("Only one SQL statement is allowed")
    return cast(exp.Expression, expressions[0])


def validate_readonly_sql(
    sql: str,
    allowed_tables: set[str],
    allowed_columns: dict[str, set[str]] | None = None,
    dialect: str = "mysql",
    allow_select_star: bool = False,
    banned_functions: set[str] | None = None,
) -> SQLValidationResult:
    raw_sql = sql.strip()
    if not raw_sql:
        raise SQLSecurityError("SQL is empty")

    expression = _parse_single(raw_sql, dialect)
    statement_type = _statement_type(expression)
    if not _is_readonly_select(expression):
        raise SQLSecurityError("Only SELECT or WITH ... SELECT statements are allowed")

    _assert_no_banned_capabilities(raw_sql, expression, banned_functions)
    _assert_star_policy(expression, allow_select_star)

    referenced_tables = _referenced_tables(expression)
    _assert_allowed_tables(referenced_tables, allowed_tables)

    normalized_allowed_columns = _normalize_allowed_columns(allowed_columns)
    referenced_columns = _collect_referenced_columns(expression, referenced_tables, normalized_allowed_columns)

    normalized_sql = expression.sql(dialect=dialect)
    return SQLValidationResult(
        normalized_sql=normalized_sql,
        referenced_tables=referenced_tables,
        referenced_columns={table: sorted(columns) for table, columns in sorted(referenced_columns.items())},
        has_limit=expression.args.get("limit") is not None,
        statement_type=statement_type,
    )


def _literal_limit_value(limit: exp.Expression | None) -> int | None:
    if limit is None:
        return None
    value = limit.args.get("expression")
    if not isinstance(value, exp.Literal) or value.is_string:
        raise SQLSecurityError("LIMIT must be a non-negative integer literal")
    try:
        parsed = int(str(value.this))
    except ValueError as exc:
        raise SQLSecurityError("LIMIT must be a non-negative integer literal") from exc
    if parsed < 0:
        raise SQLSecurityError("LIMIT must be a non-negative integer literal")
    return parsed


def enforce_select_limit(sql: str, max_rows: int, dialect: str = "mysql") -> str:
    if max_rows <= 0:
        raise SQLSecurityError("max_rows must be greater than 0")
    expression = _parse_single(sql.strip(), dialect)
    if not _is_readonly_select(expression):
        raise SQLSecurityError("Only SELECT or WITH ... SELECT statements are allowed")

    current_limit = expression.args.get("limit")
    current_value = _literal_limit_value(current_limit)
    if current_value is None:
        expression = cast(Any, expression).limit(max_rows)
    elif current_value > max_rows:
        expression.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return expression.sql(dialect=dialect)


def ensure_select_limit(sql: str, max_rows: int, dialect: str = "mysql") -> str:
    return enforce_select_limit(sql, max_rows, dialect=dialect)


def build_sql_access_policy(table_infos: Sequence[Mapping[str, Any]]) -> tuple[set[str], dict[str, set[str]]]:
    allowed_tables: set[str] = set()
    allowed_columns: dict[str, set[str]] = {}
    for table in table_infos:
        table_name = str(table.get("name") or "").strip().lower()
        if not table_name:
            continue
        allowed_tables.add(table_name)
        allowed_columns[table_name] = {
            str(column.get("name") or "").strip().lower()
            for column in table.get("columns", [])
            if str(column.get("name") or "").strip()
        }
    return allowed_tables, allowed_columns
