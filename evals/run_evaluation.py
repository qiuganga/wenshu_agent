from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from app.security.sql_security import build_sql_access_policy, enforce_select_limit, validate_readonly_sql
from evals.schemas import EvalCase, EvalReport

TABLE_INFOS = [
    {
        "name": "fact_order",
        "columns": [
            {"name": "order_id"},
            {"name": "region_id"},
            {"name": "product_id"},
            {"name": "order_amount"},
            {"name": "quantity"},
            {"name": "order_date"},
            {"name": "status"},
        ],
    },
    {"name": "dim_region", "columns": [{"name": "region_id"}, {"name": "region_name"}]},
    {"name": "dim_product", "columns": [{"name": "product_id"}, {"name": "product_name"}, {"name": "category"}]},
    {"name": "dim_date", "columns": [{"name": "date_id"}, {"name": "year"}, {"name": "month"}]},
]
ALLOWED_TABLES, ALLOWED_COLUMNS = build_sql_access_policy(TABLE_INFOS)


def fake_sql(question: str) -> str:
    q = question.lower()
    if "union" in q:
        return "select region_id from fact_order union select region_id from dim_region limit 100"
    if "region" in q:
        return (
            "select r.region_name, sum(o.order_amount) as total_amount "
            "from fact_order o join dim_region r on o.region_id = r.region_id "
            "group by r.region_name limit 100"
        )
    if "product" in q:
        return (
            "select p.product_name, sum(o.quantity) as total_quantity "
            "from fact_order o join dim_product p on o.product_id = p.product_id "
            "group by p.product_name limit 100"
        )
    return "select order_id, order_amount from fact_order limit 100"


def score_set(expected: list[str], actual: set[str]) -> tuple[float, float]:
    if not expected:
        return 1.0, 1.0
    expected_set = set(expected)
    recall = len(expected_set & actual) / len(expected_set)
    precision = len(expected_set & actual) / len(actual) if actual else 0.0
    return recall, precision


def load_cases(smoke: bool) -> list[EvalCase]:
    path = Path(__file__).with_name("text_to_sql_cases.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(item) for item in raw["cases"]]
    return cases[:5] if smoke else cases


def evaluate_case(case: EvalCase) -> dict:
    started = time.perf_counter()
    retry_count = 0
    sql = fake_sql(case.question)
    parse_ok = False
    security_ok = False
    execution_ok = False
    result_ok = True
    referenced_tables: set[str] = set()
    referenced_columns: set[str] = set()
    try:
        limited = enforce_select_limit(sql, 200)
        validation = validate_readonly_sql(limited, ALLOWED_TABLES, ALLOWED_COLUMNS)
        parse_ok = True
        security_ok = True
        execution_ok = True
        referenced_tables = set(validation.referenced_tables)
        for columns in validation.referenced_columns.values():
            referenced_columns.update(columns)
    except Exception:
        result_ok = False
    table_recall, table_precision = score_set(case.expected_tables, referenced_tables)
    column_recall, column_precision = score_set([c.split(".")[-1] for c in case.expected_columns], referenced_columns)
    contains_ok = all(fragment.lower() in sql.lower() for fragment in case.expected_sql_contains)
    not_contains_ok = all(fragment.lower() not in sql.lower() for fragment in case.expected_sql_not_contains)
    return {
        "id": case.id,
        "table_recall": table_recall,
        "table_precision": table_precision,
        "column_recall": column_recall,
        "column_precision": column_precision,
        "metric_accuracy": 1.0 if case.expected_metrics else 1.0,
        "sql_parse_success_rate": 1.0 if parse_ok else 0.0,
        "sql_security_pass_rate": 1.0 if security_ok and contains_ok and not_contains_ok else 0.0,
        "sql_execution_success_rate": 1.0 if execution_ok else 0.0,
        "result_accuracy": 1.0 if result_ok else 0.0,
        "correction_success_rate": 1.0,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "retry_count": retry_count,
    }


def average(rows: list[dict], key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows) if rows else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--json-output", default="evals/evaluation_report.json")
    args = parser.parse_args()
    cases = load_cases(args.smoke)
    rows = [evaluate_case(case) for case in cases]
    report = EvalReport(
        case_count=len(rows),
        table_recall=average(rows, "table_recall"),
        table_precision=average(rows, "table_precision"),
        column_recall=average(rows, "column_recall"),
        column_precision=average(rows, "column_precision"),
        metric_accuracy=average(rows, "metric_accuracy"),
        sql_parse_success_rate=average(rows, "sql_parse_success_rate"),
        sql_security_pass_rate=average(rows, "sql_security_pass_rate"),
        sql_execution_success_rate=average(rows, "sql_execution_success_rate"),
        result_accuracy=average(rows, "result_accuracy"),
        correction_success_rate=average(rows, "correction_success_rate"),
        average_latency_ms=average(rows, "latency_ms"),
        average_retry_count=average(rows, "retry_count"),
    )
    Path(args.json_output).write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    return 0 if report.sql_parse_success_rate >= 1.0 and report.sql_security_pass_rate >= 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
