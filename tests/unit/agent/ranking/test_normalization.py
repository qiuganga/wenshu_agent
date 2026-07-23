import math

from app.agent.ranking.normalization import normalize_aliases, normalize_text, safe_similarity_score, tokenize


def test_normalization_preserves_numbers_dates_and_basic_tokens() -> None:
    text = normalize_text("  Sales   TOP 10  2026-01-01  ")

    assert text == "sales top 10 2026-01-01"
    assert "2026" in tokenize(text)
    assert normalize_aliases(["GMV", "", "GMV"]) == ("gmv",)


def test_safe_similarity_score_rejects_missing_and_non_finite_values() -> None:
    assert safe_similarity_score(None) == 0
    assert safe_similarity_score(math.nan) == 0
    assert safe_similarity_score(math.inf) == 0
    assert safe_similarity_score(1.5) == 1
    assert safe_similarity_score(0.42) == 0.42
