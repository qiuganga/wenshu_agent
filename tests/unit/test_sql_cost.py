from app.security.sql_cost import assess_explain_json


def test_low_cost_explain_is_accepted():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ref","rows_examined_per_scan":10}}}'
    )
    assert assessment.accepted is True
    assert assessment.estimated_rows == 10


def test_estimated_rows_limit_rejected():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ref","rows_examined_per_scan":1000}}}',
        max_estimated_rows=100,
    )
    assert assessment.accepted is False
    assert "MAX_ESTIMATED_ROWS_EXCEEDED" in assessment.rejection_reasons


def test_full_scan_policy():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ALL","rows_examined_per_scan":10}}}',
        reject_full_table_scan=True,
    )
    assert assessment.accepted is False
    assert assessment.full_scan_tables == ["fact_order"]


def test_invalid_json_rejected():
    assessment = assess_explain_json("not json")
    assert assessment.accepted is False
    assert assessment.rejection_reasons == ["EXPLAIN_JSON_PARSE_FAILED"]
