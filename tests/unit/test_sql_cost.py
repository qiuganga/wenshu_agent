import json

from app.security.sql_cost import assess_explain_json


def test_index_query_is_accepted_and_extracts_table_details():
    assessment = assess_explain_json(
        """
        {
          "query_block": {
            "cost_info": {"query_cost": "35.70"},
            "table": {
              "table_name": "fact_order",
              "access_type": "ref",
              "possible_keys": ["idx_region"],
              "key": "idx_region",
              "rows_examined_per_scan": "10",
              "rows_produced_per_join": "8",
              "attached_condition": "fact_order.region_id = 1"
            }
          }
        }
        """,
        table_infos=[{"name": "fact_order", "role": "fact"}],
    )

    assert assessment.accepted is True
    assert assessment.estimated_rows == 10
    assert assessment.estimated_rows_produced == 8
    assert assessment.query_cost == 35.7
    assert assessment.access_types == {"fact_order": "ref"}
    assert assessment.keys == {"fact_order": "idx_region"}
    assert assessment.possible_keys == {"fact_order": ["idx_region"]}
    assert assessment.attached_conditions == {"fact_order": True}


def test_dimension_full_scan_is_allowed_by_default():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"dim_region","access_type":"ALL","rows_examined_per_scan":10}}}',
        table_infos=[{"name": "dim_region", "role": "dim"}],
        max_full_scan_fact_tables=0,
        allow_dimension_full_scan=True,
    )

    assert assessment.accepted is True
    assert assessment.full_scan_dimension_tables == ["dim_region"]
    assert assessment.full_scan_fact_tables == []


def test_fact_full_scan_is_rejected():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ALL","rows_examined_per_scan":10}}}',
        table_infos=[{"name": "fact_order", "role": "fact"}],
        max_full_scan_fact_tables=0,
    )

    assert assessment.accepted is False
    assert assessment.full_scan_tables == ["fact_order"]
    assert assessment.full_scan_fact_tables == ["fact_order"]
    assert "FACT_TABLE_FULL_SCAN" in assessment.rejection_reasons


def test_unknown_table_role_defaults_to_fact_for_full_scan():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"unknown_table","access_type":"ALL","rows_examined_per_scan":10}}}',
        table_infos=[],
        max_full_scan_fact_tables=0,
    )

    assert assessment.accepted is False
    assert assessment.full_scan_fact_tables == ["unknown_table"]


def test_estimated_rows_limit_rejected():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ref","rows_examined_per_scan":1000}}}',
        max_estimated_rows=100,
    )

    assert assessment.accepted is False
    assert "ESTIMATED_ROWS_EXCEEDED" in assessment.rejection_reasons


def test_query_cost_limit_rejected():
    assessment = assess_explain_json(
        '{"query_block":{"cost_info":{"query_cost":"1000.50"},"table":{"table_name":"fact_order","access_type":"ref"}}}',
        max_query_cost=100,
    )

    assert assessment.accepted is False
    assert "QUERY_COST_EXCEEDED" in assessment.rejection_reasons


def test_join_table_limit_rejected():
    assessment = assess_explain_json(
        """
        {"query_block":{"nested_loop":[
          {"table":{"table_name":"a","access_type":"ref"}},
          {"table":{"table_name":"b","access_type":"ref"}},
          {"table":{"table_name":"c","access_type":"ref"}}
        ]}}
        """,
        max_join_tables=2,
    )

    assert assessment.accepted is False
    assert assessment.table_count == 3
    assert "TOO_MANY_JOIN_TABLES" in assessment.rejection_reasons


def test_filesort_and_temporary_table_rejected_when_configured():
    assessment = assess_explain_json(
        """
        {"query_block":{
          "ordering_operation":{"using_filesort":true},
          "grouping_operation":{"using_temporary_table":true}
        }}
        """,
        reject_filesort=True,
        reject_temporary_table=True,
    )

    assert assessment.accepted is False
    assert assessment.uses_filesort is True
    assert assessment.uses_temporary_table is True
    assert "FILESORT_REJECTED" in assessment.rejection_reasons
    assert "TEMPORARY_TABLE_REJECTED" in assessment.rejection_reasons


def test_missing_cost_info_is_safe():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ref","rows_examined_per_scan":5}}}'
    )

    assert assessment.accepted is True
    assert assessment.query_cost == 0.0


def test_invalid_json_is_cost_assessment_failure():
    assessment = assess_explain_json("not json")

    assert assessment.accepted is False
    assert assessment.rejection_reasons == ["COST_ASSESSMENT_FAILED"]


def test_decimal_and_string_numeric_values_are_parsed_safely():
    assessment = assess_explain_json(
        """
        {"query_block":{
          "cost_info":{"query_cost":"12.25"},
          "table":{
            "table_name":"fact_order",
            "access_type":"ref",
            "rows_examined_per_scan":"20.9",
            "rows_produced_per_join":"11.2"
          }
        }}
        """
    )

    assert assessment.accepted is True
    assert assessment.estimated_rows == 20
    assert assessment.estimated_rows_produced == 11
    assert assessment.query_cost == 12.25


def test_non_finite_numeric_values_are_ignored():
    assessment = assess_explain_json(
        """
        {"query_block":{
          "cost_info":{"query_cost":"Infinity"},
          "table":{
            "table_name":"fact_order",
            "access_type":"ref",
            "rows_examined_per_scan":"NaN",
            "rows_produced_per_join":null
          }
        }}
        """
    )

    assert assessment.accepted is True
    assert assessment.estimated_rows == 0
    assert assessment.estimated_rows_produced == 0
    assert assessment.query_cost == 0.0


def test_multi_layer_nested_loop_is_walked():
    assessment = assess_explain_json(
        """
        {"query_block":{"nested_loop":[
          {"table":{"table_name":"fact_order","access_type":"ref","rows_examined_per_scan":100}},
          {"nested_loop":[
            {"table":{"table_name":"dim_region","access_type":"ALL","rows_examined_per_scan":5}}
          ]}
        ]}}
        """,
        table_infos=[{"name": "fact_order", "role": "fact"}, {"name": "dim_region", "role": "dimension"}],
    )

    assert assessment.accepted is True
    assert assessment.table_count == 2
    assert assessment.estimated_rows == 105
    assert assessment.full_scan_dimension_tables == ["dim_region"]


def test_deeply_nested_explain_does_not_recurse_forever():
    node = {"table": {"table_name": "fact_order", "access_type": "ref", "rows_examined_per_scan": 1}}
    for _ in range(80):
        node = {"query_block": node}

    assessment = assess_explain_json(json.dumps(node))

    assert assessment.accepted is True
