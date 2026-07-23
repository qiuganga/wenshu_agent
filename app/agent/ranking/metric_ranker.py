from __future__ import annotations

from app.agent.ranking.models import MetricCandidateFeatures, QueryRequirements, RankingPenalties, RankingWeights
from app.agent.ranking.normalization import contains_term, normalize_aliases, normalize_text, safe_similarity_score
from app.agent.state import DataAgentState, MetricInfoState, TableInfoState


class DeterministicMetricRanker:
    def __init__(self, *, weights: RankingWeights | None = None, penalties: RankingPenalties | None = None) -> None:
        self.weights = weights or RankingWeights()
        self.penalties = penalties or RankingPenalties()
        self.weights.validate()
        self.penalties.validate()

    def rank(
        self,
        state: DataAgentState,
        requirements: QueryRequirements,
        metric_infos: list[MetricInfoState],
        selected_tables: list[TableInfoState],
    ) -> list[MetricCandidateFeatures]:
        vector_scores = state.get("metric_vector_scores", {})
        selected_columns = {
            normalize_text(column.get("name", ""))
            for table in selected_tables
            for column in table.get("columns", [])
            if column.get("name")
        }
        features = [
            self._score_metric(metric, requirements, vector_scores, selected_columns)
            for metric in self._dedupe(metric_infos)
        ]
        return sorted(
            features,
            key=lambda item: (
                -item.total_score,
                -item.relevant_column_coverage_score,
                -item.vector_similarity_score,
                item.metric_name,
            ),
        )

    def _score_metric(
        self,
        metric: MetricInfoState,
        requirements: QueryRequirements,
        vector_scores: dict[str, float],
        selected_columns: set[str],
    ) -> MetricCandidateFeatures:
        metric_name = metric.get("name", "")
        terms = requirements.keyword_tokens + requirements.matched_metric_names
        reason_codes: set[str] = set()
        lexical = 0.0
        if contains_term(metric_name, terms):
            lexical = 1.0
            reason_codes.add("METRIC_NAME_MATCH")
        elif contains_term(metric.get("description", ""), terms):
            lexical = 0.7
            reason_codes.add("METRIC_DESCRIPTION_MATCH")
        alias = 1.0 if set(normalize_aliases(metric.get("alias"))) & set(terms) else 0.0
        if alias:
            reason_codes.add("METRIC_ALIAS_MATCH")
        vector = safe_similarity_score(vector_scores.get(metric_name))
        if vector > 0:
            reason_codes.add("METRIC_VECTOR_MATCH")
        relevant_columns = {normalize_text(column) for column in metric.get("relevant_columns", []) if column}
        matched_requirement_columns = set(requirements.matched_column_names) | set(
            requirements.matched_value_column_names
        )
        coverage = (
            len(relevant_columns & matched_requirement_columns) / len(relevant_columns) if relevant_columns else 0.0
        )
        if coverage >= 1:
            reason_codes.add("METRIC_COLUMNS_COVERED")
        elif coverage > 0:
            reason_codes.add("METRIC_PARTIAL_COLUMN_COVERAGE")
        support = len(relevant_columns & selected_columns) / len(relevant_columns) if relevant_columns else 0.0
        if support > 0:
            reason_codes.add("METRIC_SUPPORTED_BY_SELECTED_TABLES")
        else:
            reason_codes.add("METRIC_UNSUPPORTED_BY_SELECTED_TABLES")
        raw = (
            self.weights.lexical * lexical
            + self.weights.alias * alias
            + self.weights.vector * vector
            + self.weights.coverage * coverage
            + self.weights.metric_support * support
        )
        if relevant_columns and support <= 0:
            raw -= self.penalties.unsupported_metric
        return MetricCandidateFeatures(
            metric_name=metric_name,
            lexical_match_score=lexical,
            alias_match_score=alias,
            vector_similarity_score=vector,
            relevant_column_coverage_score=coverage,
            selected_table_support_score=support,
            total_score=max(0.0, min(1.0, raw)),
            reason_codes=tuple(sorted(reason_codes)),
        )

    @staticmethod
    def _dedupe(metric_infos: list[MetricInfoState]) -> list[MetricInfoState]:
        seen: set[str] = set()
        deduped: list[MetricInfoState] = []
        for metric in metric_infos:
            name = metric.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(metric)
        return deduped
