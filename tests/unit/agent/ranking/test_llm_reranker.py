from app.agent.ranking.reranker import (
    CandidateRerankResult,
    constrained_metric_selection,
    constrained_table_selection,
    parse_rerank_result,
)


def test_table_reranker_rejects_fabricated_duplicates_and_limits_count() -> None:
    result = constrained_table_selection(
        deterministic_names=["orders", "products", "regions"],
        max_selected=2,
        llm_result=CandidateRerankResult(
            ordered_candidate_names=["missing", "products", "products", "orders"],
            selected_candidate_names=["missing", "products", "products", "orders"],
        ),
    )

    assert result.selected_tables == ["products", "orders"]
    assert result.selection_source == "llm_reranked"


def test_table_reranker_keeps_bridge_table_and_falls_back_on_empty() -> None:
    keep_bridge = constrained_table_selection(
        deterministic_names=["orders", "bridge"],
        max_selected=2,
        bridge_names={"bridge"},
        llm_result=CandidateRerankResult(selected_candidate_names=["orders"]),
    )
    fallback = constrained_table_selection(
        deterministic_names=["orders"],
        max_selected=1,
        llm_result=CandidateRerankResult(selected_candidate_names=["missing"]),
    )

    assert keep_bridge.selected_tables == ["orders", "bridge"]
    assert fallback.selection_source == "deterministic_fallback"


def test_metric_reranker_filters_unknown_and_parse_failure() -> None:
    parsed = parse_rerank_result({"selected_candidate_names": ["GMV", "missing"]})
    assert parsed is not None

    result = constrained_metric_selection(
        deterministic_names=["GMV", "AOV"],
        max_selected=1,
        llm_result=parsed,
    )

    assert result.selected_metrics == ["GMV"]
    assert parse_rerank_result("not-json") is None
