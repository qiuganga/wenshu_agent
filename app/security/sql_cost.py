from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class SQLCostAssessment(BaseModel):
    estimated_rows: int = 0
    table_count: int = 0
    full_scan_tables: list[str] = Field(default_factory=list)
    uses_filesort: bool = False
    uses_temporary_table: bool = False
    access_types: dict[str, str] = Field(default_factory=dict)
    accepted: bool = True
    rejection_reasons: list[str] = Field(default_factory=list)


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def assess_explain_json(
    explain_json: str,
    max_estimated_rows: int = 100_000,
    max_join_tables: int = 8,
    reject_full_table_scan: bool = False,
    reject_filesort: bool = False,
    reject_temporary_table: bool = False,
) -> SQLCostAssessment:
    try:
        parsed = json.loads(explain_json or "{}")
    except json.JSONDecodeError:
        return SQLCostAssessment(accepted=False, rejection_reasons=["EXPLAIN_JSON_PARSE_FAILED"])

    assessment = SQLCostAssessment()
    for node in _walk(parsed):
        table = node.get("table")
        if isinstance(table, dict):
            table_name = str(table.get("table_name") or table.get("table") or "unknown")
            rows = int(table.get("rows_examined_per_scan") or table.get("rows") or 0)
            access_type = str(table.get("access_type") or "")
            assessment.estimated_rows += rows
            assessment.table_count += 1
            if access_type:
                assessment.access_types[table_name] = access_type
            if access_type.upper() == "ALL":
                assessment.full_scan_tables.append(table_name)
        if "filesort" in node or node.get("using_filesort") is True:
            assessment.uses_filesort = True
        if "temporary_table" in node or node.get("using_temporary_table") is True:
            assessment.uses_temporary_table = True

    if assessment.estimated_rows > max_estimated_rows:
        assessment.rejection_reasons.append("MAX_ESTIMATED_ROWS_EXCEEDED")
    if assessment.table_count > max_join_tables:
        assessment.rejection_reasons.append("MAX_JOIN_TABLES_EXCEEDED")
    if reject_full_table_scan and assessment.full_scan_tables:
        assessment.rejection_reasons.append("FULL_TABLE_SCAN_REJECTED")
    if reject_filesort and assessment.uses_filesort:
        assessment.rejection_reasons.append("FILESORT_REJECTED")
    if reject_temporary_table and assessment.uses_temporary_table:
        assessment.rejection_reasons.append("TEMPORARY_TABLE_REJECTED")
    assessment.accepted = not assessment.rejection_reasons
    return assessment
