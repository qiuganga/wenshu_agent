from __future__ import annotations

from app.agent.ranking.models import CandidateSetCoverage, CoverageResult, QueryRequirements, TableCandidateFeatures
from app.agent.ranking.normalization import contains_term, normalize_aliases, normalize_text
from app.agent.state import TableInfoState


class ColumnCoverageCalculator:
    def calculate(self, requirements: QueryRequirements, table_info: TableInfoState) -> CoverageResult:
        requirement_terms = tuple(dict.fromkeys(requirements.requirement_terms))
        if not requirement_terms:
            return CoverageResult(0.0, (), (), ("NO_REQUIREMENT_COVERAGE",))
        covered: list[str] = []
        reason_codes: set[str] = set()
        for term in requirement_terms:
            if self._table_covers_requirement(term, table_info, reason_codes):
                covered.append(term)
        uncovered = [term for term in requirement_terms if term not in set(covered)]
        score = len(covered) / len(requirement_terms) if requirement_terms else 0.0
        if score >= 1:
            reason_codes.add("FULL_REQUIREMENT_COVERAGE")
        elif score > 0:
            reason_codes.add("PARTIAL_REQUIREMENT_COVERAGE")
        else:
            reason_codes.add("NO_REQUIREMENT_COVERAGE")
        return CoverageResult(score, tuple(covered), tuple(uncovered), tuple(sorted(reason_codes)))

    def _table_covers_requirement(self, term: str, table_info: TableInfoState, reason_codes: set[str]) -> bool:
        normalized_term = normalize_text(term)
        for column in table_info.get("columns", []):
            if normalized_term == normalize_text(column.get("name", "")):
                reason_codes.add("DIRECT_COLUMN_MATCH")
                return True
            if normalized_term in normalize_aliases(column.get("alias")):
                reason_codes.add("COLUMN_ALIAS_MATCH")
                return True
            if contains_term(column.get("description", ""), [normalized_term]):
                reason_codes.add("DIRECT_COLUMN_MATCH")
                return True
        return False


class CandidateSetCoverageCalculator:
    def greedy_cover(
        self,
        *,
        ranked_features: list[TableCandidateFeatures],
        requirements: QueryRequirements,
        max_tables: int,
    ) -> CandidateSetCoverage:
        remaining = set(requirements.requirement_terms)
        selected: list[str] = []
        covered: set[str] = set()
        for feature in ranked_features:
            gain = set(feature.covered_requirements) - covered
            if not selected or gain:
                selected.append(feature.table_name)
                covered.update(feature.covered_requirements)
                remaining -= gain
            if len(selected) >= max_tables or not remaining:
                break
        reason_codes = ["FULL_COVERAGE" if not remaining else "PARTIAL_COVERAGE"]
        return CandidateSetCoverage(selected, sorted(covered), sorted(remaining), [], 0, reason_codes)
