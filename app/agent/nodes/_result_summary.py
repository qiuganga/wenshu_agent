from __future__ import annotations

from statistics import mean
from typing import Any

from app.config.app_config import app_config
from app.security.data_masking import mask_rows

DEFAULT_SAMPLE_N = 20


def summarize_result(
    rows: list[dict[str, Any]], sample_n: int | None = None, truncated: bool = False
) -> dict[str, Any]:
    effective_sample_n = sample_n if sample_n is not None else app_config.agent.result_sample_rows or DEFAULT_SAMPLE_N
    row_count = len(rows)
    columns = list(rows[0].keys()) if rows else []
    numeric_stats: dict[str, dict[str, float | int]] = {}

    for column in columns:
        values = [row[column] for row in rows if isinstance(row.get(column), int | float)]
        if values:
            numeric_stats[column] = {
                "count": len(values),
                "sum": sum(values),
                "avg": mean(values),
                "min": min(values),
                "max": max(values),
            }

    sample = mask_rows(rows[:effective_sample_n], app_config.security.sensitive_fields)
    return {
        "row_count": row_count,
        "columns": columns,
        "numeric_stats": numeric_stats,
        "sample": sample,
        "truncated": truncated or row_count > effective_sample_n,
    }
