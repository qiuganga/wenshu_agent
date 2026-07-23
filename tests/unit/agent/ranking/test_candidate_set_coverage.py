from app.agent.ranking.coverage import CandidateSetCoverageCalculator, ColumnCoverageCalculator
from app.agent.ranking.models import QueryRequirements, TableCandidateFeatures


def test_column_coverage_full_partial_and_empty_requirements() -> None:
    calculator = ColumnCoverageCalculator()
    table = {"name": "orders", "columns": [{"name": "amount", "alias": ["sales_amount"]}]}

    full = calculator.calculate(QueryRequirements(keyword_tokens=("amount",)), table)
    partial = calculator.calculate(QueryRequirements(keyword_tokens=("amount", "region")), table)
    empty = calculator.calculate(QueryRequirements(), table)

    assert full.coverage_score == 1
    assert "FULL_REQUIREMENT_COVERAGE" in full.reason_codes
    assert partial.coverage_score == 0.5
    assert empty.coverage_score == 0


def test_candidate_set_coverage_greedy_selects_marginal_gain() -> None:
    result = CandidateSetCoverageCalculator().greedy_cover(
        ranked_features=[
            TableCandidateFeatures("orders", covered_requirements=("amount",), total_score=0.9),
            TableCandidateFeatures("products", covered_requirements=("category",), total_score=0.8),
            TableCandidateFeatures("unused", covered_requirements=(), total_score=0.7),
        ],
        requirements=QueryRequirements(keyword_tokens=("amount", "category")),
        max_tables=3,
    )

    assert result.selected_tables == ["orders", "products"]
    assert result.reason_codes == ["FULL_COVERAGE"]
