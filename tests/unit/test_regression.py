from app.evaluation.regression import RegressionRunner
from app.evaluation.report import EvaluationCaseResult, EvaluationReport


def test_regression_runner_fails_when_drop_exceeds_threshold():
    result = RegressionRunner(threshold=0.05).compare({"accuracy": 0.9}, {"accuracy": 0.8})

    assert result.passed is False
    assert result.regressions["accuracy"] == 0.09999999999999998


def test_regression_runner_passes_small_drop():
    result = RegressionRunner(threshold=0.2).compare({"accuracy": 0.9}, {"accuracy": 0.8})

    assert result.passed is True


def test_evaluation_report_generates_safe_json_shape():
    report = EvaluationReport(
        dataset_version="v1",
        dataset_hash="hash",
        cases=[
            EvaluationCaseResult(
                case_id="case-1",
                success=True,
                scores={"table_selection_accuracy": 1.0, "answer_relevance": 0.8},
                latency_ms=20,
                cache_hit=True,
            )
        ],
    )

    payload = report.to_dict()

    assert payload["total_cases"] == 1
    assert payload["success_rate"] == 1.0
    assert payload["sql_accuracy"] == 1.0
    assert payload["answer_score"] == 0.8
    assert "raw_result" not in str(payload)
