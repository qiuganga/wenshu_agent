import copy

import pytest

from app.config.app_config import AppConfig, validate_runtime_config


def valid_config() -> AppConfig:
    config = AppConfig()
    config.llm.api_key = "test-key"
    config.db_dw.user = "readonly_user"
    return config


def test_new_agent_cost_config_defaults_are_backward_compatible():
    config = valid_config()

    validate_runtime_config(config)

    assert config.agent.max_query_cost == 100000.0
    assert config.agent.max_full_scan_fact_tables == 0
    assert config.agent.max_unknown_full_scan_rows == 10000
    assert config.agent.allow_dimension_full_scan is True
    assert config.agent.explain_timeout_seconds == 5


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_query_cost", 0, "agent.max_query_cost must be greater than 0"),
        ("max_query_cost", 1_000_000_001, "agent.max_query_cost must be <= 1000000000"),
        ("max_join_tables", 65, "agent.max_join_tables must be <= 64"),
        ("max_full_scan_fact_tables", -1, "agent.max_full_scan_fact_tables must be >= 0"),
        ("max_unknown_full_scan_rows", 0, "agent.max_unknown_full_scan_rows must be >= 1"),
        ("explain_timeout_seconds", 0, "agent.explain_timeout_seconds must be greater than 0"),
        ("explain_timeout_seconds", 61, "agent.explain_timeout_seconds must be <= 60"),
    ],
)
def test_new_agent_cost_config_validation(field, value, message):
    config = valid_config()
    setattr(config.agent, field, value)

    with pytest.raises(ValueError, match=message):
        validate_runtime_config(config)


def test_full_scan_fact_limit_must_not_exceed_join_limit():
    config = valid_config()
    config.agent.max_join_tables = 2
    config.agent.max_full_scan_fact_tables = 3

    with pytest.raises(ValueError, match="agent.max_full_scan_fact_tables must be <= agent.max_join_tables"):
        validate_runtime_config(copy.deepcopy(config))


def test_unknown_full_scan_limit_must_not_exceed_estimated_rows_limit():
    config = valid_config()
    config.agent.max_estimated_rows = 100
    config.agent.max_unknown_full_scan_rows = 101

    with pytest.raises(ValueError, match="agent.max_unknown_full_scan_rows must be <= agent.max_estimated_rows"):
        validate_runtime_config(copy.deepcopy(config))
