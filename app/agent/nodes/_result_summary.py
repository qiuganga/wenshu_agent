from numbers import Number
from typing import Any

DEFAULT_SAMPLE_N = 50


def summarize_result(rows: list[dict[str, Any]], sample_n: int = DEFAULT_SAMPLE_N) -> dict[str, Any]:
    row_count = len(rows)
    columns = list(rows[0].keys()) if rows else []

    numeric_stats: dict[str, dict[str, float]] = {}
    for col in columns:
        values = [row[col] for row in rows if isinstance(row.get(col), Number) and not isinstance(row.get(col), bool)]
        if values:
            numeric_stats[col] = {
                "sum": float(sum(values)),
                "min": float(min(values)),
                "max": float(max(values)),
                "avg": float(sum(values) / len(values)),
            }

    sample = rows[:sample_n]
    return {
        "row_count": row_count,
        "columns": columns,
        "numeric_stats": numeric_stats,
        "sample": sample,
        "truncated": row_count > sample_n,
    }
