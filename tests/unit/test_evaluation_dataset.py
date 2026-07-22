import json

import pytest

from app.evaluation.dataset import EvaluationCase, load_evaluation_dataset


def test_evaluation_case_safe_snapshot_hashes_question():
    case = EvaluationCase.from_dict(
        {
            "id": "case-1",
            "question": "hello",
            "expected_sql": "select amount from fact_order",
            "expected_tables": ["fact_order"],
            "expected_tool": "sql_query",
            "metadata": {"domain": "sales"},
        }
    )

    safe = case.to_safe_dict()

    assert safe["id"] == "case-1"
    assert safe["question_hash"] != "hello"
    assert safe["has_expected_sql"] is True
    assert safe["expected_tools"] == ["sql_query"]


def test_load_json_dataset_version_and_hash(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            {
                "dataset_version": "v1",
                "cases": [{"id": "case-1", "question": "hello", "expected_tables": ["fact_order"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dataset = load_evaluation_dataset(path)

    assert dataset.version == "v1"
    assert len(dataset.cases) == 1
    assert len(dataset.dataset_hash) == 64


def test_load_jsonl_dataset(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text('{"id":"case-1","question":"hello"}\n', encoding="utf-8")

    dataset = load_evaluation_dataset(path)

    assert dataset.version == "unknown"
    assert dataset.cases[0].id == "case-1"


def test_dataset_rejects_forbidden_sensitive_fields():
    with pytest.raises(ValueError):
        EvaluationCase.from_dict({"id": "case-1", "question": "hello", "password": "value"})
