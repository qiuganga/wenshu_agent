from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

UNKNOWN_TABLE_ROLE = "fact"
FACT_TABLE_ROLES = {"fact", "fact_table", "factual"}
DIMENSION_TABLE_ROLES = {"dim", "dimension", "dimension_table", "lookup"}


class SQLCostAssessment(BaseModel):
    accepted: bool = True
    estimated_rows: int = 0
    estimated_rows_produced: int = 0
    query_cost: float = 0.0
    table_count: int = 0
    full_scan_tables: list[str] = Field(default_factory=list)
    full_scan_fact_tables: list[str] = Field(default_factory=list)
    full_scan_dimension_tables: list[str] = Field(default_factory=list)
    uses_filesort: bool = False
    uses_temporary_table: bool = False
    access_types: dict[str, str] = Field(default_factory=dict)
    keys: dict[str, str | None] = Field(default_factory=dict)
    possible_keys: dict[str, list[str]] = Field(default_factory=dict)
    attached_conditions: dict[str, bool] = Field(default_factory=dict)
    rejection_reasons: list[str] = Field(default_factory=list)


def _walk(node: Any, *, max_depth: int = 64):
    if max_depth < 0:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, max_depth=max_depth - 1)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, max_depth=max_depth - 1)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | str | Decimal):
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() else None
    return None


def _to_int(value: Any) -> int:
    number = _to_decimal(value)
    if number is None or number < 0:
        return 0
    return int(number)


def _to_float(value: Any) -> float:
    number = _to_decimal(value)
    if number is None or number < 0:
        return 0.0
    result = float(number)
    return result if math.isfinite(result) else 0.0


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _table_roles(table_infos: Sequence[Mapping[str, Any]] | None) -> dict[str, str]:
    roles: dict[str, str] = {}
    for table_info in table_infos or []:
        name = table_info.get("name")
        if not name:
            continue
        role = str(table_info.get("role") or UNKNOWN_TABLE_ROLE).lower()
        if role in DIMENSION_TABLE_ROLES:
            roles[str(name)] = "dimension"
        elif role in FACT_TABLE_ROLES:
            roles[str(name)] = "fact"
        else:
            roles[str(name)] = UNKNOWN_TABLE_ROLE
    return roles


def _is_dimension_table(table_name: str, roles: Mapping[str, str]) -> bool:
    return roles.get(table_name, UNKNOWN_TABLE_ROLE) == "dimension"


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def assess_explain_json(
    explain_json: str,
    *,
    table_infos: Sequence[Mapping[str, Any]] | None = None,
    max_estimated_rows: int = 100_000,
    max_query_cost: float = 100_000.0,
    max_join_tables: int = 8,
    max_full_scan_fact_tables: int = 0,
    allow_dimension_full_scan: bool = True,
    reject_full_table_scan: bool = False,
    reject_filesort: bool = False,
    reject_temporary_table: bool = False,
) -> SQLCostAssessment:
    try:
        parsed = json.loads(explain_json or "{}")
    except json.JSONDecodeError:
        return SQLCostAssessment(accepted=False, rejection_reasons=["COST_ASSESSMENT_FAILED"])

    assessment = SQLCostAssessment()
    roles = _table_roles(table_infos)
    for node in _walk(parsed):
        if "cost_info" in node and isinstance(node["cost_info"], dict):
            assessment.query_cost = max(assessment.query_cost, _to_float(node["cost_info"].get("query_cost")))
        table = node.get("table")
        if isinstance(table, dict):
            table_name = str(table.get("table_name") or table.get("table") or "unknown")
            rows = _to_int(table.get("rows_examined_per_scan") or table.get("rows") or 0)
            rows_produced = _to_int(table.get("rows_produced_per_join") or 0)
            access_type = str(table.get("access_type") or "")
            assessment.estimated_rows += rows
            assessment.estimated_rows_produced += rows_produced
            assessment.table_count += 1
            if access_type:
                assessment.access_types[table_name] = access_type
            assessment.keys[table_name] = table.get("key")
            assessment.possible_keys[table_name] = _string_list(table.get("possible_keys"))
            assessment.attached_conditions[table_name] = table.get("attached_condition") is not None
            if access_type.upper() == "ALL":
                _append_unique(assessment.full_scan_tables, table_name)
                if _is_dimension_table(table_name, roles):
                    _append_unique(assessment.full_scan_dimension_tables, table_name)
                else:
                    _append_unique(assessment.full_scan_fact_tables, table_name)
        if "filesort" in node or node.get("using_filesort") is True:
            assessment.uses_filesort = True
        if "temporary_table" in node or node.get("using_temporary_table") is True:
            assessment.uses_temporary_table = True

    if assessment.estimated_rows > max_estimated_rows:
        assessment.rejection_reasons.append("ESTIMATED_ROWS_EXCEEDED")
    if assessment.query_cost > max_query_cost:
        assessment.rejection_reasons.append("QUERY_COST_EXCEEDED")
    if assessment.table_count > max_join_tables:
        assessment.rejection_reasons.append("TOO_MANY_JOIN_TABLES")
    if len(assessment.full_scan_fact_tables) > max_full_scan_fact_tables:
        assessment.rejection_reasons.append("FACT_TABLE_FULL_SCAN")
    if reject_full_table_scan and assessment.full_scan_tables:
        assessment.rejection_reasons.append("FULL_TABLE_SCAN_REJECTED")
    if not allow_dimension_full_scan and assessment.full_scan_dimension_tables:
        assessment.rejection_reasons.append("DIMENSION_TABLE_FULL_SCAN")
    if reject_filesort and assessment.uses_filesort:
        assessment.rejection_reasons.append("FILESORT_REJECTED")
    if reject_temporary_table and assessment.uses_temporary_table:
        assessment.rejection_reasons.append("TEMPORARY_TABLE_REJECTED")
    assessment.accepted = not assessment.rejection_reasons
    return assessment
