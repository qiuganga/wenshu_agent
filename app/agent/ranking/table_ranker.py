from __future__ import annotations

from app.agent.ranking.coverage import ColumnCoverageCalculator
from app.agent.ranking.models import QueryRequirements, RankingPenalties, RankingWeights, TableCandidateFeatures
from app.agent.ranking.normalization import contains_term, normalize_aliases, normalize_text, safe_similarity_score
from app.agent.ranking.relationship_graph import TableRelationshipGraph
from app.agent.state import DataAgentState, TableInfoState


class DeterministicTableRanker:
    def __init__(
        self,
        *,
        weights: RankingWeights | None = None,
        penalties: RankingPenalties | None = None,
        relationship_graph: TableRelationshipGraph | None = None,
    ) -> None:
        self.weights = weights or RankingWeights()
        self.penalties = penalties or RankingPenalties()
        self.weights.validate()
        self.penalties.validate()
        self.coverage = ColumnCoverageCalculator()
        self.relationship_graph = relationship_graph or TableRelationshipGraph()

    def rank(
        self,
        state: DataAgentState,
        requirements: QueryRequirements,
        table_infos: list[TableInfoState],
    ) -> list[TableCandidateFeatures]:
        vector_scores = state.get("table_vector_scores", {})
        value_table_names = {
            normalize_text(value.get("table_name", ""))
            for value in state.get("retrieved_values", [])
            if value.get("table_name")
        }
        metric_columns = {
            normalize_text(column)
            for metric in state.get("metric_infos", [])
            for column in metric.get("relevant_columns", [])
            if column
        }
        features = [
            self._score_table(table, requirements, vector_scores, value_table_names, metric_columns)
            for table in self._dedupe(table_infos)
        ]
        return sorted(
            features,
            key=lambda item: (
                -item.total_score,
                -item.column_coverage_score,
                -item.vector_similarity_score,
                item.table_name,
            ),
        )

    def _score_table(
        self,
        table: TableInfoState,
        requirements: QueryRequirements,
        vector_scores: dict[str, float],
        value_table_names: set[str],
        metric_columns: set[str],
    ) -> TableCandidateFeatures:
        table_name = table.get("name", "")
        table_role = table.get("role", "")
        terms = requirements.keyword_tokens
        reason_codes: set[str] = set()
        lexical = 0.0
        if contains_term(table_name, terms):
            lexical = max(lexical, 1.0)
            reason_codes.add("TABLE_NAME_MATCH")
        if contains_term(table.get("description", ""), terms):
            lexical = max(lexical, 0.7)
            reason_codes.add("TABLE_DESCRIPTION_MATCH")
        alias = 0.0
        for column in table.get("columns", []):
            if contains_term(column.get("name", ""), terms):
                lexical = max(lexical, 0.8)
                reason_codes.add("COLUMN_NAME_MATCH")
            if contains_term(column.get("description", ""), terms):
                lexical = max(lexical, 0.5)
                reason_codes.add("COLUMN_DESCRIPTION_MATCH")
            if set(normalize_aliases(column.get("alias"))) & set(terms):
                alias = max(alias, 1.0)
                reason_codes.add("COLUMN_ALIAS_MATCH")
        vector = safe_similarity_score(vector_scores.get(table_name))
        if vector > 0:
            reason_codes.add("VECTOR_MATCH")
        coverage = self.coverage.calculate(requirements, table)
        reason_codes.update(coverage.reason_codes)
        value_match = 1.0 if normalize_text(table_name) in value_table_names else 0.0
        if value_match:
            reason_codes.add("VALUE_COLUMN_MATCH")
        table_columns = {normalize_text(column.get("name", "")) for column in table.get("columns", [])}
        metric_support = 1.0 if table_columns & metric_columns else 0.0
        if metric_support:
            reason_codes.add("METRIC_COLUMN_SUPPORT")
        relationship_distance = 0
        relationship_score = 1.0
        join_path_available = True
        if requirements.likely_fact_table_required and table_role == "dimension":
            relationship_score = 0.7
            reason_codes.add("ROLE_INTENT_PARTIAL_MATCH")
        raw_score = (
            self.weights.lexical * lexical
            + self.weights.alias * alias
            + self.weights.vector * vector
            + self.weights.coverage * coverage.coverage_score
            + self.weights.value * value_match
            + self.weights.metric_support * metric_support
            + self.weights.relationship * relationship_score
        )
        total = max(0.0, min(1.0, raw_score))
        return TableCandidateFeatures(
            table_name=table_name,
            table_role=table_role,
            lexical_match_score=lexical,
            alias_match_score=alias,
            vector_similarity_score=vector,
            column_coverage_score=coverage.coverage_score,
            value_match_score=value_match,
            metric_support_score=metric_support,
            relationship_score=relationship_score,
            relationship_distance=relationship_distance,
            join_path_available=join_path_available,
            total_score=total,
            reason_codes=tuple(sorted(reason_codes)),
            covered_requirements=coverage.covered_requirements,
        )

    @staticmethod
    def _dedupe(table_infos: list[TableInfoState]) -> list[TableInfoState]:
        seen: set[str] = set()
        deduped: list[TableInfoState] = []
        for table in table_infos:
            name = table.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(table)
        return deduped
