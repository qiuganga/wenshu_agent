from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from statistics import mean
from typing import Any

from app.config.app_config import app_config
from app.security.data_masking import is_sensitive_field, mask_row

DEFAULT_SAMPLE_N = 20
DEFAULT_VALUE_MAX_CHARS = 500
TRUNCATION_MARKER = "...[truncated]"
MAX_CONTAINER_ITEMS = 20
MAX_SERIALIZATION_DEPTH = 4
NON_MAPPING_VALUE_COLUMN = "value"
MEMORY_ADDRESS_PATTERN = re.compile(r"\b(?:at\s+)?0x[0-9a-fA-F]+\b")


def _safe_str(value: object) -> str:
    try:
        text = str(value)
    except Exception:
        text = f"<unprintable {value.__class__.__name__}>"
    return MEMORY_ADDRESS_PATTERN.sub("", text).strip()


def _stringify_key(key: Any) -> str:
    return key if isinstance(key, str) else _safe_str(key)


def _iter_unique_items(row: Mapping[Any, Any], limit: int | None = None):
    seen_keys: set[str] = set()
    yielded = 0
    for raw_key, value in row.items():
        key = _stringify_key(raw_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        yield key, value
        yielded += 1
        if limit is not None and yielded >= limit:
            break


def _extract_columns(rows: list[Any]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            if NON_MAPPING_VALUE_COLUMN not in seen:
                seen.add(NON_MAPPING_VALUE_COLUMN)
                columns.append(NON_MAPPING_VALUE_COLUMN)
            continue
        for key, _ in _iter_unique_items(row):
            if key in seen:
                continue
            seen.add(key)
            columns.append(key)
    return columns


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    marker = TRUNCATION_MARKER
    if max_chars <= len(marker):
        return marker[:max_chars]
    return f"{value[: max_chars - len(marker)]}{marker}"


def _is_supported_numeric(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _json_number(value: int | float | Decimal) -> int | float | None:
    if isinstance(value, Decimal):
        try:
            as_float = float(value)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(as_float):
            return None
        return as_float
    return value


def _safe_sort_key(value: Any) -> str:
    return _truncate_text(_safe_str(value), 100)


def _safe_sample_value(value: Any, max_chars: int, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return _truncate_text(value, max_chars)
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        return _truncate_text(f"<bytes len={len(raw)} hex={raw[:32].hex()}>", max_chars)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if depth >= MAX_SERIALIZATION_DEPTH:
        return "<max-depth-reached>"
    if isinstance(value, list | tuple):
        return [_safe_sample_value(item, max_chars, depth + 1) for item in list(value)[:MAX_CONTAINER_ITEMS]]
    if isinstance(value, set):
        return [
            _safe_sample_value(item, max_chars, depth + 1)
            for item in sorted(value, key=_safe_sort_key)[:MAX_CONTAINER_ITEMS]
        ]
    if isinstance(value, Mapping):
        return {
            _truncate_text(key, max_chars): _safe_sample_value(item, max_chars, depth + 1)
            for key, item in _iter_unique_items(value, limit=MAX_CONTAINER_ITEMS)
        }
    class_name = value.__class__.__name__
    safe_text = _safe_str(value)
    return _truncate_text(f"<{class_name}: {safe_text}>", max_chars)


def _safe_sample_row(row: Any, sensitive_fields: list[str], max_chars: int) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {NON_MAPPING_VALUE_COLUMN: _safe_sample_value(row, max_chars)}
    safe_row = {key: _safe_sample_value(value, max_chars) for key, value in _iter_unique_items(row)}
    return mask_row(safe_row, sensitive_fields)


def _numeric_stats(
    rows: list[Any],
    columns: list[str],
    sensitive_fields: list[str],
) -> dict[str, dict[str, float | int]]:
    stats: dict[str, dict[str, float | int]] = {}
    for column in columns:
        if is_sensitive_field(column, sensitive_fields):
            continue
        json_values: list[int | float] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            for key, value in _iter_unique_items(row):
                if key != column or not _is_supported_numeric(value):
                    continue
                json_value = _json_number(value)
                if json_value is not None:
                    json_values.append(json_value)
        if not json_values:
            continue
        stats[column] = {
            "count": len(json_values),
            "sum": sum(json_values),
            "avg": mean(json_values),
            "min": min(json_values),
            "max": max(json_values),
        }
    return stats


def summarize_result(
    rows: list[Any],
    sample_n: int | None = None,
    truncated: bool = False,
    sensitive_fields: list[str] | None = None,
    sample_value_max_chars: int | None = None,
) -> dict[str, Any]:
    effective_sample_n = sample_n if sample_n is not None else app_config.agent.result_sample_rows or DEFAULT_SAMPLE_N
    effective_value_max_chars = (
        sample_value_max_chars
        if sample_value_max_chars is not None
        else app_config.agent.result_sample_value_max_chars or DEFAULT_VALUE_MAX_CHARS
    )
    effective_sensitive_fields = sensitive_fields or app_config.security.sensitive_fields

    row_count = len(rows)
    columns = _extract_columns(rows)
    sample_rows = rows[:effective_sample_n]
    sample = [_safe_sample_row(row, effective_sensitive_fields, effective_value_max_chars) for row in sample_rows]
    query_result_truncated = bool(truncated)
    sample_truncated = row_count > effective_sample_n

    return {
        "row_count": row_count,
        "columns": columns,
        "numeric_stats": _numeric_stats(rows, columns, effective_sensitive_fields),
        "sample": sample,
        "query_result_truncated": query_result_truncated,
        "sample_truncated": sample_truncated,
        "truncated": query_result_truncated or sample_truncated,
    }
