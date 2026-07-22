from app.governance.complexity import ComplexityLevel, RequestComplexityClassifier


def test_complexity_classifier_detects_simple_standard_complex_and_heavy() -> None:
    classifier = RequestComplexityClassifier()

    assert classifier.classify("hello").complexity_level == ComplexityLevel.SIMPLE
    assert classifier.classify("查询销售金额").complexity_level == ComplexityLevel.STANDARD
    assert classifier.classify("查询销售趋势并分析原因").complexity_level == ComplexityLevel.COMPLEX
    heavy = classifier.classify(
        "查询销售趋势并分析原因，同时结合知识库文档和多代理协作",
        estimated_tables=6,
        requires_multi_agent=True,
        estimated_tool_calls=3,
    )
    assert heavy.complexity_level == ComplexityLevel.HEAVY
    assert "multi_agent_required" in heavy.reason_codes


def test_complexity_classifier_preserves_numeric_date_and_negation_context() -> None:
    result = RequestComplexityClassifier().classify("统计 2026-01-01 之后没有退款的订单金额")

    assert result.complexity_level in {ComplexityLevel.STANDARD, ComplexityLevel.COMPLEX}
    assert "sql_required" in result.reason_codes
