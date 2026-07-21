from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

TABLE_ROLE_FACT = "fact"
TABLE_ROLE_DIMENSION = "dimension"
TABLE_ROLE_UNKNOWN = "unknown"

FACT_TABLE_ROLES = {"fact", "fact_table", "factual", "事实表"}
DIMENSION_TABLE_ROLES = {"dim", "dimension", "dimension_table", "lookup", "维度表"}
TABLE_ROLE_VALUES = FACT_TABLE_ROLES | DIMENSION_TABLE_ROLES

QUERY_COST_QUERY_BLOCK = "query_block.query_cost"
QUERY_COST_OUTER_PREFIX = "outer_prefix_cost"
QUERY_COST_OUTER_READ_EVAL = "outer_read_eval_cost"
QUERY_COST_FALLBACK_SUM = "fallback_component_sum"
QUERY_COST_UNAVAILABLE = "unavailable"

MAX_EXPLAIN_DEPTH = 64
MAX_EXPLAIN_NODES = 10_000


class SQLCostAssessment(BaseModel):
    accepted: bool = True
    estimated_rows: int = 0
    estimated_rows_produced: int = 0
    query_cost: float = 0.0
    query_cost_source: str = QUERY_COST_UNAVAILABLE
    query_cost_components: dict[str, Any] = Field(default_factory=dict)
    table_count: int = 0
    table_roles: dict[str, str] = Field(default_factory=dict)
    full_scan_tables: list[str] = Field(default_factory=list)
    full_scan_fact_tables: list[str] = Field(default_factory=list)
    full_scan_dimension_tables: list[str] = Field(default_factory=list)
    full_scan_unknown_tables: list[str] = Field(default_factory=list)
    uses_filesort: bool = False
    uses_temporary_table: bool = False
    access_types: dict[str, str] = Field(default_factory=dict)
    keys: dict[str, str | None] = Field(default_factory=dict)
    possible_keys: dict[str, list[str]] = Field(default_factory=dict)
    attached_conditions: dict[str, bool] = Field(default_factory=dict)
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass
class ExplainCostSummary:
    query_cost: float = 0.0
    query_cost_source: str = QUERY_COST_UNAVAILABLE
    query_cost_components: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _TraversalBudget:
    visited: set[int] = field(default_factory=set)
    nodes: int = 0


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _normalize_marker(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().lower()
    return text or None


def _role_from_marker(value: Any) -> str | None:
    marker = _normalize_marker(value)
    if marker in FACT_TABLE_ROLES:
        return TABLE_ROLE_FACT
    if marker in DIMENSION_TABLE_ROLES:
        return TABLE_ROLE_DIMENSION
    return None


def _metadata_mapping(table_info: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = table_info.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _role_from_structured_metadata(table_info: Mapping[str, Any]) -> str | None:
    metadata = _metadata_mapping(table_info)
    sources = (metadata, table_info)
    for source in sources:
        if source.get("is_fact") is True:
            return TABLE_ROLE_FACT
        if source.get("is_dimension") is True:
            return TABLE_ROLE_DIMENSION
    for key in ("table_category", "entity_type"):
        for source in sources:
            role = _role_from_marker(source.get(key))
            if role:
                return role
    return None


def _role_from_table_name(table_name: str) -> str:
    lower_name = table_name.lower()
    if lower_name.startswith(("dim_", "d_")) or lower_name.endswith("_dim"):
        return TABLE_ROLE_DIMENSION
    if lower_name.startswith(("fact_", "fct_")) or lower_name.endswith("_fact"):
        return TABLE_ROLE_FACT
    return TABLE_ROLE_UNKNOWN


def classify_table_role(table_info: Mapping[str, Any] | None = None, table_name: str | None = None) -> str:
    table_info = table_info or {}
    name = str(table_name or table_info.get("name") or "")
    for key in ("role", "type", "table_type"):
        role = _role_from_marker(table_info.get(key))
        if role:
            return role
    metadata_role = _role_from_structured_metadata(table_info)
    if metadata_role:
        return metadata_role
    if name:
        return _role_from_table_name(name)
    return TABLE_ROLE_UNKNOWN


def _table_infos_by_name(table_infos: Sequence[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    infos: dict[str, Mapping[str, Any]] = {}
    for table_info in table_infos or []:
        name = table_info.get("name")
        if name and str(name) not in infos:
            infos[str(name)] = table_info
    return infos


def _table_role(table_name: str, table_infos: Mapping[str, Mapping[str, Any]]) -> str:
    return classify_table_role(table_infos.get(table_name), table_name)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | str | Decimal):
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() and number >= 0 else None
    return None


def _to_int(value: Any) -> int:
    number = _to_decimal(value)
    return int(number) if number is not None else 0


def _to_float(value: Any) -> float | None:
    number = _to_decimal(value)
    if number is None:
        return None
    result = float(number)
    return result if math.isfinite(result) and result >= 0 else None


def _cost_value(cost_info: Mapping[str, Any] | None, key: str) -> float | None:
    if not isinstance(cost_info, Mapping):
        return None
    return _to_float(cost_info.get(key))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _parse_explain(explain: Any) -> Any:
    if isinstance(explain, str):
        try:
            return json.loads(explain or "{}")
        except json.JSONDecodeError:
            return None
    return explain


def _walk(node: Any, *, max_depth: int = MAX_EXPLAIN_DEPTH, max_nodes: int = MAX_EXPLAIN_NODES):
    budget = _TraversalBudget()

    def _inner(current: Any, depth: int):
        if budget.nodes >= max_nodes or depth < 0:
            return
        if isinstance(current, Mapping):
            object_id = id(current)
            if object_id in budget.visited:
                return
            budget.visited.add(object_id)
            budget.nodes += 1
            yield current
            for value in current.values():
                yield from _inner(value, depth - 1)
        elif isinstance(current, list | tuple):
            object_id = id(current)
            if object_id in budget.visited:
                return
            budget.visited.add(object_id)
            budget.nodes += 1
            for item in current:
                yield from _inner(item, depth - 1)

    yield from _inner(node, max_depth)


def _outer_table_cost_info(query_block: Mapping[str, Any]) -> Mapping[str, Any] | None:
    table = query_block.get("table")
    if isinstance(table, Mapping) and isinstance(table.get("cost_info"), Mapping):
        return table["cost_info"]
    nested_loop = query_block.get("nested_loop")
    if isinstance(nested_loop, Sequence) and not isinstance(nested_loop, str | bytes | bytearray):
        for item in nested_loop:
            if isinstance(item, Mapping):
                table = item.get("table")
                if isinstance(table, Mapping) and isinstance(table.get("cost_info"), Mapping):
                    return table["cost_info"]
    return None


def _query_block(parsed: Any) -> Mapping[str, Any] | None:
    if isinstance(parsed, Mapping):
        block = parsed.get("query_block")
        return block if isinstance(block, Mapping) else parsed
    return None


def _fallback_cost_sum(parsed: Any) -> tuple[float, dict[str, Any]]:
    total = 0.0
    component_count = 0
    for node in _walk(parsed):
        cost_info = node.get("cost_info")
        if not isinstance(cost_info, Mapping):
            continue
        read_cost = _cost_value(cost_info, "read_cost")
        eval_cost = _cost_value(cost_info, "eval_cost")
        query_cost = _cost_value(cost_info, "query_cost")
        prefix_cost = _cost_value(cost_info, "prefix_cost")
        if read_cost is not None or eval_cost is not None:
            total += read_cost or 0.0
            total += eval_cost or 0.0
            component_count += 1
        elif query_cost is not None:
            total += query_cost
            component_count += 1
        elif prefix_cost is not None:
            total = max(total, prefix_cost)
            component_count += 1
    return total, {"fallback_component_count": component_count, "fallback_component_sum": total}


def normalize_explain_cost(explain: Any) -> ExplainCostSummary:
    parsed = _parse_explain(explain)
    if parsed is None:
        return ExplainCostSummary(warnings=["QUERY_COST_UNAVAILABLE"])

    block = _query_block(parsed)
    query_block_cost_info = block.get("cost_info") if isinstance(block, Mapping) else None
    top_query_cost = _cost_value(query_block_cost_info, "query_cost")
    if top_query_cost is not None:
        return ExplainCostSummary(
            query_cost=top_query_cost,
            query_cost_source=QUERY_COST_QUERY_BLOCK,
            query_cost_components={"query_block_query_cost": top_query_cost},
        )

    outer_cost_info = _outer_table_cost_info(block) if block is not None else None
    outer_prefix_cost = _cost_value(outer_cost_info, "prefix_cost")
    if outer_prefix_cost is not None:
        return ExplainCostSummary(
            query_cost=outer_prefix_cost,
            query_cost_source=QUERY_COST_OUTER_PREFIX,
            query_cost_components={"outer_prefix_cost": outer_prefix_cost},
        )

    outer_read_cost = _cost_value(outer_cost_info, "read_cost")
    outer_eval_cost = _cost_value(outer_cost_info, "eval_cost")
    if outer_read_cost is not None or outer_eval_cost is not None:
        query_cost = (outer_read_cost or 0.0) + (outer_eval_cost or 0.0)
        return ExplainCostSummary(
            query_cost=query_cost,
            query_cost_source=QUERY_COST_OUTER_READ_EVAL,
            query_cost_components={
                "outer_read_cost": outer_read_cost or 0.0,
                "outer_eval_cost": outer_eval_cost or 0.0,
            },
        )

    fallback_cost, components = _fallback_cost_sum(parsed)
    if fallback_cost > 0:
        return ExplainCostSummary(
            query_cost=fallback_cost,
            query_cost_source=QUERY_COST_FALLBACK_SUM,
            query_cost_components=components,
            warnings=["QUERY_COST_FALLBACK_USED"],
        )
    return ExplainCostSummary(
        query_cost=0.0,
        query_cost_source=QUERY_COST_UNAVAILABLE,
        query_cost_components={},
        warnings=["QUERY_COST_UNAVAILABLE"],
    )


def assess_explain_json(
    explain_json: str,
    *,
    table_infos: Sequence[Mapping[str, Any]] | None = None,
    max_estimated_rows: int = 100_000,
    max_query_cost: float = 100_000.0,
    max_join_tables: int = 8,
    max_full_scan_fact_tables: int = 0,
    max_unknown_full_scan_rows: int = 10_000,
    allow_dimension_full_scan: bool = True,
    reject_full_table_scan: bool = False,
    reject_filesort: bool = False,
    reject_temporary_table: bool = False,
) -> SQLCostAssessment:
    parsed = _parse_explain(explain_json)
    if parsed is None:
        return SQLCostAssessment(
            accepted=False,
            rejection_reasons=["COST_ASSESSMENT_FAILED"],
            warnings=["QUERY_COST_UNAVAILABLE"],
        )

    assessment = SQLCostAssessment()
    table_info_by_name = _table_infos_by_name(table_infos)
    cost_summary = normalize_explain_cost(parsed)
    assessment.query_cost = cost_summary.query_cost
    assessment.query_cost_source = cost_summary.query_cost_source
    assessment.query_cost_components = cost_summary.query_cost_components
    assessment.warnings.extend(cost_summary.warnings)

    for node in _walk(parsed):
        table = node.get("table")
        if isinstance(table, Mapping):
            table_name = str(table.get("table_name") or table.get("table") or "unknown")
            rows = _to_int(table.get("rows_examined_per_scan") or table.get("rows") or 0)
            rows_produced = _to_int(table.get("rows_produced_per_join") or 0)
            access_type = str(table.get("access_type") or "")
            table_role = _table_role(table_name, table_info_by_name)
            assessment.table_roles[table_name] = table_role
            if table_role == TABLE_ROLE_UNKNOWN:
                _append_unique(assessment.warnings, "UNKNOWN_TABLE_ROLE")

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
                if table_role == TABLE_ROLE_DIMENSION:
                    _append_unique(assessment.full_scan_dimension_tables, table_name)
                elif table_role == TABLE_ROLE_FACT:
                    _append_unique(assessment.full_scan_fact_tables, table_name)
                else:
                    _append_unique(assessment.full_scan_unknown_tables, table_name)
                    if rows > max_unknown_full_scan_rows:
                        _append_unique(assessment.rejection_reasons, "UNKNOWN_TABLE_FULL_SCAN_EXCEEDED")
                    else:
                        _append_unique(assessment.warnings, "UNKNOWN_TABLE_FULL_SCAN_ALLOWED")
        if "filesort" in node or node.get("using_filesort") is True:
            assessment.uses_filesort = True
        if "temporary_table" in node or node.get("using_temporary_table") is True:
            assessment.uses_temporary_table = True

    if assessment.estimated_rows > max_estimated_rows:
        _append_unique(assessment.rejection_reasons, "ESTIMATED_ROWS_EXCEEDED")
    if assessment.query_cost > max_query_cost:
        _append_unique(assessment.rejection_reasons, "QUERY_COST_EXCEEDED")
    if assessment.table_count > max_join_tables:
        _append_unique(assessment.rejection_reasons, "TOO_MANY_JOIN_TABLES")
    if len(assessment.full_scan_fact_tables) > max_full_scan_fact_tables:
        _append_unique(assessment.rejection_reasons, "FACT_TABLE_FULL_SCAN")
    if reject_full_table_scan and assessment.full_scan_tables:
        _append_unique(assessment.rejection_reasons, "FULL_TABLE_SCAN_REJECTED")
    if not allow_dimension_full_scan and assessment.full_scan_dimension_tables:
        _append_unique(assessment.rejection_reasons, "DIMENSION_TABLE_FULL_SCAN")
    if reject_filesort and assessment.uses_filesort:
        _append_unique(assessment.rejection_reasons, "FILESORT_REJECTED")
    if reject_temporary_table and assessment.uses_temporary_table:
        _append_unique(assessment.rejection_reasons, "TEMPORARY_TABLE_REJECTED")
    assessment.accepted = not assessment.rejection_reasons
    return assessment
