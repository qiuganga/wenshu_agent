from types import SimpleNamespace

from app.agent.nodes import filter_metric as filter_metric_module
from app.agent.nodes import filter_table as filter_table_module
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.ranking.reranker import CandidateRerankResult


class FakeRankingLLM:
    def __init__(self, result=None, fail: bool = False) -> None:
        self.result = result or CandidateRerankResult()
        self.fail = fail
        self.payloads = []

    async def ainvoke_structured(self, prompt_name, payload, schema, parser=None):
        self.payloads.append((prompt_name, payload, schema))
        if self.fail:
            raise RuntimeError("provider failed")
        return self.result


def _runtime():
    return SimpleNamespace(stream_writer=lambda event: None)


def _table(name, column):
    return {
        "name": name,
        "role": "fact",
        "description": f"{name} table",
        "columns": [{"name": column, "description": column, "alias": [column]}],
    }


def _metric(name, column):
    return {"name": name, "description": name, "alias": [name], "relevant_columns": [column]}


async def test_hybrid_table_ranking_constrains_llm_and_keeps_safe_state(monkeypatch) -> None:
    fake_llm = FakeRankingLLM(
        CandidateRerankResult(
            ordered_candidate_names=["missing", "products", "orders"],
            selected_candidate_names=["missing", "products", "orders"],
            reason_codes=["LLM_RERANK"],
        )
    )
    monkeypatch.setattr(filter_table_module, "llm", fake_llm)
    state = {
        "query": "统计销售金额和商品类别",
        "keywords": ["销售金额", "类别"],
        "table_infos": [_table("orders", "销售金额"), _table("products", "类别")],
        "table_vector_scores": {"orders": 0.8, "products": 0.7},
        "retrieved_values": [],
        "retrieved_metrics": [],
        "metric_infos": [],
    }

    result = await filter_table(state, _runtime())

    assert [table["name"] for table in result["table_infos"]] == ["products", "orders"]
    assert result["table_selection_source"] == "llm_reranked"
    assert "missing" not in [table["name"] for table in result["table_infos"]]
    assert "table_candidate_scores" in result
    assert "embedding" not in str(result).lower()


async def test_hybrid_metric_ranking_falls_back_when_llm_fails(monkeypatch) -> None:
    fake_llm = FakeRankingLLM(fail=True)
    monkeypatch.setattr(filter_metric_module, "llm", fake_llm)
    state = {
        "query": "GMV 销售金额",
        "keywords": ["GMV"],
        "metric_infos": [_metric("GMV", "amount"), _metric("Refund", "refund_amount")],
        "metric_vector_scores": {"GMV": 0.9},
        "table_infos": [_table("orders", "amount")],
    }

    result = await filter_metric(state, _runtime())

    assert [metric["name"] for metric in result["metric_infos"]][0] == "GMV"
    assert result["metric_selection_source"] == "deterministic_fallback"
    assert fake_llm.payloads
