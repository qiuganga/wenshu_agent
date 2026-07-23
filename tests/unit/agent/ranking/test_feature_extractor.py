from app.agent.ranking.feature_extractor import QueryRequirementExtractor


def test_feature_extractor_uses_existing_state_without_extra_llm_call() -> None:
    requirements = QueryRequirementExtractor().extract(
        {
            "query": "统计 2026 年销售金额 Top 10",
            "keywords": ["销售金额"],
            "retrieved_columns": [{"name": "amount"}],
            "retrieved_values": [{"column_name": "region"}],
            "retrieved_metrics": [{"name": "GMV"}],
        }
    )

    assert "销售金额" in requirements.keyword_tokens
    assert "amount" in requirements.matched_column_names
    assert "region" in requirements.matched_value_column_names
    assert "gmv" in requirements.matched_metric_names
    assert requirements.aggregation_intent is True
    assert requirements.ordering_intent is True
    assert requirements.time_related_intent is True
