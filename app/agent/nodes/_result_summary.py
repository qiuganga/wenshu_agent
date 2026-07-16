from numbers import Number
from typing import Any

# 喂给 LLM 的默认采样行数
DEFAULT_SAMPLE_N = 50


def summarize_result(rows: list[dict], sample_n: int = DEFAULT_SAMPLE_N) -> dict[str, Any]:
    """将查询结果压缩成"小而全"的上下文，供 LLM 解读。

    返回字段：
    - row_count:    结果总行数
    - columns:      列名列表
    - numeric_stats: 数值列的 sum/min/max/avg
    - sample:       采样行（前 sample_n 行）
    - truncated:    是否发生截断
    """
    row_count = len(rows)
    columns = list(rows[0].keys()) if rows else []

    numeric_stats: dict[str, dict[str, float]] = {}
    for col in columns:
        values = [row[col] for row in rows
                  if isinstance(row[col], Number) and not isinstance(row[col], bool)]
        if values:
            numeric_stats[col] = {
                "sum": sum(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
            }

    sample = rows[:sample_n]

    return {
        "row_count": row_count,
        "columns": columns,
        "numeric_stats": numeric_stats,
        "sample": sample,
        "truncated": row_count > sample_n,
    }
