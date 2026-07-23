from app.agent.ranking.feature_extractor import QueryRequirementExtractor
from app.agent.ranking.metric_ranker import DeterministicMetricRanker


def test_metric_ranker_scores_selected_table_support_and_penalty() -> None:
    state = {"query": "GMV 销售金额", "keywords": ["GMV"], "metric_vector_scores": {"GMV": 0.9}}
    requirements = QueryRequirementExtractor().extract(state)
    metrics = [
        {"name": "GMV", "description": "sales", "alias": ["销售额"], "relevant_columns": ["amount"]},
        {"name": "Refund", "description": "refund", "alias": [], "relevant_columns": ["refund_amount"]},
    ]
    selected_tables = [{"name": "orders", "columns": [{"name": "amount"}]}]

    ranked = DeterministicMetricRanker().rank(state, requirements, metrics, selected_tables)

    assert [item.metric_name for item in ranked] == ["GMV", "Refund"]
    assert "METRIC_SUPPORTED_BY_SELECTED_TABLES" in ranked[0].reason_codes
    assert "METRIC_UNSUPPORTED_BY_SELECTED_TABLES" in ranked[1].reason_codes
