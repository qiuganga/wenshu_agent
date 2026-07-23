from __future__ import annotations

from app.agent.ranking.models import QueryRequirements
from app.agent.ranking.normalization import normalize_aliases, tokenize
from app.agent.state import DataAgentState

AGGREGATION_TERMS = {"sum", "count", "avg", "平均", "总额", "统计", "数量", "金额"}
GROUPING_TERMS = {"by", "group", "每", "按", "分组", "地区", "类别"}
TIME_TERMS = {"日", "月", "年", "季度", "today", "month", "year", "202"}
COMPARISON_TERMS = {"比", "同比", "环比", "compare", "versus", "vs", "差异"}
ORDERING_TERMS = {"top", "排名", "最高", "最低", "前", "后"}
FACT_TERMS = {"销售", "订单", "金额", "收入", "流水", "事实", "fact"}


class QueryRequirementExtractor:
    def extract(self, state: DataAgentState) -> QueryRequirements:
        query = state.get("normalized_query") or state.get("query", "")
        query_tokens = list(tokenize(query))
        keyword_tokens = list(
            dict.fromkeys(
                [
                    *query_tokens,
                    *[token for keyword in state.get("keywords", []) for token in tokenize(keyword)],
                ]
            )
        )
        matched_columns: list[str] = []
        for column in state.get("retrieved_columns", []):
            matched_columns.extend(normalize_aliases(column.get("name")))
        matched_value_columns: list[str] = []
        for value in state.get("retrieved_values", []):
            matched_value_columns.extend(normalize_aliases(value.get("column_name")))
        matched_metrics: list[str] = []
        for metric in state.get("retrieved_metrics", []):
            matched_metrics.extend(normalize_aliases(metric.get("name")))
        all_tokens = set(keyword_tokens)
        return QueryRequirements(
            keyword_tokens=tuple(dict.fromkeys(keyword_tokens)),
            matched_column_names=tuple(dict.fromkeys(matched_columns)),
            matched_value_column_names=tuple(dict.fromkeys(matched_value_columns)),
            matched_metric_names=tuple(dict.fromkeys(matched_metrics)),
            aggregation_intent=bool(all_tokens & AGGREGATION_TERMS),
            grouping_intent=bool(all_tokens & GROUPING_TERMS),
            time_related_intent=any(any(term in token for term in TIME_TERMS) for token in all_tokens),
            comparison_intent=bool(all_tokens & COMPARISON_TERMS),
            ordering_intent=bool(all_tokens & ORDERING_TERMS),
            likely_fact_table_required=bool(all_tokens & FACT_TERMS),
        )
