import json
from decimal import Decimal

import pytest

from app.security.sql_cost import assess_explain_json, classify_table_role, normalize_explain_cost


@pytest.mark.parametrize(
    ("table_info", "table_name", "expected"),
    [
        ({"name": "orders", "role": "fact"}, "orders", "fact"),
        ({"name": "orders", "role": "FACT_TABLE"}, "orders", "fact"),
        ({"name": "orders", "role": "事实表"}, "orders", "fact"),
        ({"name": "region", "role": "dimension"}, "region", "dimension"),
        ({"name": "region", "role": "DIM"}, "region", "dimension"),
        ({"name": "region", "role": "维度表"}, "region", "dimension"),
        ({"name": "orders", "metadata": {"is_fact": True}}, "orders", "fact"),
        ({"name": "region", "metadata": {"is_dimension": True}}, "region", "dimension"),
        ({"name": "orders", "metadata": {"table_category": "fact_table"}}, "orders", "fact"),
        ({"name": "region", "metadata": {"entity_type": "dimension_table"}}, "region", "dimension"),
        ({"name": "dim_region"}, "dim_region", "dimension"),
        ({"name": "d_region"}, "d_region", "dimension"),
        ({"name": "region_dim"}, "region_dim", "dimension"),
        ({"name": "fact_order"}, "fact_order", "fact"),
        ({"name": "fct_order"}, "fct_order", "fact"),
        ({"name": "order_fact"}, "order_fact", "fact"),
        ({"name": "order_dimension_snapshot"}, "order_dimension_snapshot", "unknown"),
        ({"name": "factor_score"}, "factor_score", "unknown"),
    ],
)
def test_classify_table_role_priority_and_aliases(table_info, table_name, expected):
    assert classify_table_role(table_info, table_name) == expected


def test_classify_table_role_explicit_marker_wins_over_conflicting_metadata():
    table_info = {"name": "dim_order", "role": "fact", "metadata": {"is_dimension": True}}

    assert classify_table_role(table_info) == "fact"


def test_classify_table_role_structured_metadata_conflict_is_predictable():
    table_info = {"name": "ambiguous_table", "metadata": {"is_fact": True, "is_dimension": True}}

    assert classify_table_role(table_info) == "fact"


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
    assert assessment.query_cost_source == "query_block.query_cost"
    assert assessment.table_roles == {"fact_order": "fact"}
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


def test_unknown_small_full_scan_is_allowed_with_warning():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"unknown_table","access_type":"ALL","rows_examined_per_scan":10}}}',
        table_infos=[],
        max_full_scan_fact_tables=0,
        max_unknown_full_scan_rows=100,
    )

    assert assessment.accepted is True
    assert assessment.full_scan_fact_tables == []
    assert assessment.full_scan_unknown_tables == ["unknown_table"]
    assert "UNKNOWN_TABLE_ROLE" in assessment.warnings
    assert "UNKNOWN_TABLE_FULL_SCAN_ALLOWED" in assessment.warnings


def test_unknown_large_full_scan_is_rejected():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"unknown_table","access_type":"ALL","rows_examined_per_scan":1000}}}',
        table_infos=[],
        max_unknown_full_scan_rows=100,
    )

    assert assessment.accepted is False
    assert assessment.full_scan_fact_tables == []
    assert assessment.full_scan_unknown_tables == ["unknown_table"]
    assert "UNKNOWN_TABLE_FULL_SCAN_EXCEEDED" in assessment.rejection_reasons


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


def test_dimension_full_scan_can_be_rejected_by_config():
    assessment = assess_explain_json(
        '{"query_block":{"table":{"table_name":"dim_region","access_type":"ALL","rows_examined_per_scan":10}}}',
        table_infos=[{"name": "dim_region", "role": "dimension"}],
        allow_dimension_full_scan=False,
    )

    assert assessment.accepted is False
    assert assessment.full_scan_dimension_tables == ["dim_region"]
    assert "DIMENSION_TABLE_FULL_SCAN" in assessment.rejection_reasons


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
    assert assessment.query_cost_source == "unavailable"
    assert "QUERY_COST_UNAVAILABLE" in assessment.warnings


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


def test_decimal_query_cost_is_supported():
    summary = normalize_explain_cost({"query_block": {"cost_info": {"query_cost": Decimal("42.5")}}})

    assert summary.query_cost == 42.5
    assert summary.query_cost_source == "query_block.query_cost"


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
    assert assessment.query_cost_source == "unavailable"


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "-1", "", "bad", None])
def test_invalid_query_cost_values_are_unavailable(value):
    summary = normalize_explain_cost({"query_block": {"cost_info": {"query_cost": value}}})

    assert summary.query_cost == 0.0
    assert summary.query_cost_source == "unavailable"
    assert "QUERY_COST_UNAVAILABLE" in summary.warnings


def test_query_cost_top_level_query_block_has_priority_over_nested_costs():
    summary = normalize_explain_cost(
        {
            "query_block": {
                "cost_info": {"query_cost": "50"},
                "nested_loop": [
                    {"table": {"table_name": "fact_order", "cost_info": {"prefix_cost": "999"}}},
                ],
            }
        }
    )

    assert summary.query_cost == 50.0
    assert summary.query_cost_source == "query_block.query_cost"


def test_query_cost_uses_outer_prefix_when_top_missing():
    summary = normalize_explain_cost(
        {"query_block": {"table": {"table_name": "fact_order", "cost_info": {"prefix_cost": "25"}}}}
    )

    assert summary.query_cost == 25.0
    assert summary.query_cost_source == "outer_prefix_cost"


def test_query_cost_uses_outer_read_eval_when_prefix_missing():
    summary = normalize_explain_cost(
        {"query_block": {"table": {"table_name": "fact_order", "cost_info": {"read_cost": "10.5", "eval_cost": "2.5"}}}}
    )

    assert summary.query_cost == 13.0
    assert summary.query_cost_source == "outer_read_eval_cost"


def test_query_cost_fallback_sums_components_without_prefix_double_counting():
    summary = normalize_explain_cost(
        {
            "query_block": {
                "ordering_operation": {"cost_info": {"read_cost": "3", "eval_cost": "2", "prefix_cost": "999"}}
            }
        }
    )

    assert summary.query_cost == 5.0
    assert summary.query_cost_source == "fallback_component_sum"
    assert "QUERY_COST_FALLBACK_USED" in summary.warnings


def test_query_cost_nested_loop_uses_first_outer_table_prefix():
    summary = normalize_explain_cost(
        {
            "query_block": {
                "nested_loop": [
                    {"table": {"table_name": "fact_order", "cost_info": {"prefix_cost": "15"}}},
                    {"table": {"table_name": "dim_region", "cost_info": {"prefix_cost": "20"}}},
                ]
            }
        }
    )

    assert summary.query_cost == 15.0
    assert summary.query_cost_source == "outer_prefix_cost"


def test_query_cost_fallback_handles_grouping_materialized_and_attached_subquery():
    summary = normalize_explain_cost(
        {
            "query_block": {
                "grouping_operation": {"cost_info": {"read_cost": "2", "eval_cost": "1"}},
                "duplicates_removal": {"cost_info": {"read_cost": "3", "eval_cost": "1"}},
                "materialized_from_subquery": {
                    "query_block": {"table": {"cost_info": {"read_cost": "4", "eval_cost": "1"}}}
                },
                "attached_subqueries": [{"query_block": {"cost_info": {"query_cost": "5"}}}],
            }
        }
    )

    assert summary.query_cost == 17.0
    assert summary.query_cost_source == "fallback_component_sum"


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


def test_cycle_reference_is_safe_for_normalizer():
    node = {}
    node["query_block"] = node

    summary = normalize_explain_cost(node)

    assert summary.query_cost == 0.0
    assert summary.query_cost_source == "unavailable"


def test_large_node_count_is_bounded():
    explain = {
        "query_block": {"nested_loop": [{"cost_info": {"read_cost": "1", "eval_cost": "1"}} for _ in range(11000)]}
    }

    summary = normalize_explain_cost(explain)

    assert summary.query_cost_source == "fallback_component_sum"
