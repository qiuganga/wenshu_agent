from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoredCandidate[T]:
    payload: T
    score: float = 0.0


@dataclass(frozen=True)
class RankingWeights:
    lexical: float = 0.15
    alias: float = 0.10
    vector: float = 0.20
    coverage: float = 0.25
    value: float = 0.10
    metric_support: float = 0.10
    relationship: float = 0.10

    def validate(self) -> None:
        values = [
            self.lexical,
            self.alias,
            self.vector,
            self.coverage,
            self.value,
            self.metric_support,
            self.relationship,
        ]
        if any(value < 0 for value in values):
            raise ValueError("ranking weights must be >= 0")
        if sum(values) <= 0:
            raise ValueError("at least one ranking weight must be > 0")


@dataclass(frozen=True)
class RankingPenalties:
    disconnected: float = 0.20
    excessive_join: float = 0.05
    unsupported_metric: float = 0.25

    def validate(self) -> None:
        if self.disconnected < 0 or self.excessive_join < 0 or self.unsupported_metric < 0:
            raise ValueError("ranking penalties must be >= 0")


@dataclass(frozen=True)
class QueryRequirements:
    keyword_tokens: tuple[str, ...] = ()
    matched_column_names: tuple[str, ...] = ()
    matched_value_column_names: tuple[str, ...] = ()
    matched_metric_names: tuple[str, ...] = ()
    required_semantic_roles: tuple[str, ...] = ()
    aggregation_intent: bool = False
    grouping_intent: bool = False
    time_related_intent: bool = False
    comparison_intent: bool = False
    ordering_intent: bool = False
    likely_fact_table_required: bool = False

    @property
    def requirement_terms(self) -> tuple[str, ...]:
        terms = list(self.keyword_tokens)
        terms.extend(self.matched_column_names)
        terms.extend(self.matched_value_column_names)
        terms.extend(self.matched_metric_names)
        return tuple(dict.fromkeys(term for term in terms if term))


@dataclass(frozen=True)
class CoverageResult:
    coverage_score: float
    covered_requirements: tuple[str, ...]
    uncovered_requirements: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class TableCandidateFeatures:
    table_name: str
    table_role: str = ""
    lexical_match_score: float = 0.0
    alias_match_score: float = 0.0
    vector_similarity_score: float = 0.0
    column_coverage_score: float = 0.0
    value_match_score: float = 0.0
    metric_support_score: float = 0.0
    relationship_score: float = 0.0
    relationship_distance: int | None = None
    join_path_available: bool = False
    total_score: float = 0.0
    reason_codes: tuple[str, ...] = ()
    covered_requirements: tuple[str, ...] = ()

    def safe_summary(self) -> dict[str, object]:
        return {
            "table_name": self.table_name,
            "table_role": self.table_role,
            "score_bucket": round(self.total_score, 3),
            "covered_requirement_count": len(self.covered_requirements),
            "relationship_distance": self.relationship_distance,
            "join_path_available": self.join_path_available,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class MetricCandidateFeatures:
    metric_name: str
    lexical_match_score: float = 0.0
    alias_match_score: float = 0.0
    vector_similarity_score: float = 0.0
    relevant_column_coverage_score: float = 0.0
    selected_table_support_score: float = 0.0
    total_score: float = 0.0
    reason_codes: tuple[str, ...] = ()

    def safe_summary(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "score_bucket": round(self.total_score, 3),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class FinalTableSelection:
    selected_tables: list[str]
    deterministic_ranking: list[str]
    llm_ranking: list[str] = field(default_factory=list)
    selection_source: str = "deterministic"
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinalMetricSelection:
    selected_metrics: list[str]
    deterministic_ranking: list[str]
    llm_ranking: list[str] = field(default_factory=list)
    selection_source: str = "deterministic"
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateSetCoverage:
    selected_tables: list[str]
    covered_requirements: list[str]
    uncovered_requirements: list[str]
    bridge_tables: list[str]
    total_relationship_cost: int
    reason_codes: list[str]
