from app.evaluation.answer_metrics import evaluate_answer
from app.evaluation.judge import JudgeInput, LLMJudge, RuleJudge


def scores(metrics):
    return {metric.name: metric.score for metric in metrics}


def test_answer_metrics_relevance_completeness_and_faithfulness():
    result = scores(evaluate_answer("华南销售额最高，金额为 100", "华南销售额最高", context="金额 100"))

    assert result["answer_relevance"] == 1.0
    assert result["answer_completeness"] == 1.0
    assert result["answer_faithfulness"] == 1.0


def test_answer_metrics_detect_unfaithful_number():
    result = scores(evaluate_answer("金额为 999", "金额", context="金额 100"))

    assert result["answer_faithfulness"] == 0.0


def test_rule_judge_uses_rule_based_metrics():
    result = RuleJudge().evaluate(JudgeInput(question_hash="h", answer="hello world", expected_answer="hello"))

    assert result


def test_llm_judge_rejects_unsafe_summary():
    try:
        LLMJudge().evaluate(JudgeInput(question_hash="h", answer="ok", safe_summary={"raw_sql": "select 1"}))
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("LLMJudge should reject unsafe summary")
