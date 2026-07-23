import pytest

from app.agent.ranking.feature_extractor import QueryRequirementExtractor
from app.agent.ranking.models import RankingWeights
from app.agent.ranking.table_ranker import DeterministicTableRanker


def _table(name: str, column_name: str, *, role: str = "fact"):
    return {
        "name": name,
        "role": role,
        "description": f"{name} table",
        "columns": [
            {
                "name": column_name,
                "description": f"{column_name} description",
                "alias": [f"{column_name}_alias"],
            }
        ],
    }


def test_table_ranker_scores_matches_and_stable_tie_breakers() -> None:
    state = {
        "query": "统计销售金额",
        "keywords": ["销售金额"],
        "retrieved_values": [{"table_name": "orders"}],
        "metric_infos": [{"relevant_columns": ["amount"]}],
        "table_vector_scores": {"orders": 0.8, "users": 0.8},
    }
    requirements = QueryRequirementExtractor().extract(state)

    ranked = DeterministicTableRanker().rank(state, requirements, [_table("users", "name"), _table("orders", "amount")])

    assert [item.table_name for item in ranked] == ["orders", "users"]
    assert "VALUE_COLUMN_MATCH" in ranked[0].reason_codes
    assert "METRIC_COLUMN_SUPPORT" in ranked[0].reason_codes


def test_table_ranker_rejects_invalid_weights() -> None:
    with pytest.raises(ValueError):
        DeterministicTableRanker(weights=RankingWeights(lexical=-1))

    with pytest.raises(ValueError):
        DeterministicTableRanker(weights=RankingWeights(0, 0, 0, 0, 0, 0, 0))
