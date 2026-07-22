from app.governance.finops import FinOpsAggregator, FinOpsRecord


def test_finops_aggregates_safe_dimensions_and_separates_estimates() -> None:
    aggregator = FinOpsAggregator()
    aggregator.add(
        FinOpsRecord(
            time_bucket="2026-01-01T00",
            tenant_hash="tenant-hash",
            model_name="m1",
            agent_name="sql_agent",
            cache_hit=False,
            usage_source="estimated",
            pricing_version="v1",
            input_tokens=10,
            output_tokens=5,
            estimated_cost_minor_units=2,
            retry_cost_minor_units=1,
        )
    )
    aggregator.add(
        FinOpsRecord(
            time_bucket="2026-01-01T00",
            tenant_hash="tenant-hash",
            model_name="m1",
            agent_name="sql_agent",
            cache_hit=False,
            usage_source="estimated",
            pricing_version="v1",
            cache_saved_tokens=10,
            cache_saved_cost_estimate_minor_units=1,
        )
    )

    report = aggregator.aggregate()[0]
    assert report["request_count"] == 2
    assert report["total_tokens"] == 15
    assert report["estimated_cost_minor_units"] == 2
    assert report["cache_saved_cost_estimate_minor_units"] == 1
    assert "query" not in report
    assert "prompt" not in report
