import pytest

from app.config.app_config import AppConfig, validate_runtime_config


def production_config() -> AppConfig:
    config = AppConfig()
    config.runtime.environment = "prod"
    config.app.debug = False
    config.security.production_mode = True
    config.llm.api_key = "prod-llm-key"
    config.db_dw.user = "readonly_user"
    config.db_dw.password = "prod-dw-pass"
    config.db_meta.password = "prod-meta-pass"
    return config


def test_production_config_accepts_safe_defaults():
    config = production_config()

    validate_runtime_config(config)

    assert config.server.host == "0.0.0.0"
    assert config.server.port == 8000
    assert config.server.shutdown_timeout_seconds == 5


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("environment", "stage", "runtime.environment must be dev, test or prod"),
    ],
)
def test_runtime_environment_validation(field, value, message):
    config = production_config()
    setattr(config.runtime, field, value)

    with pytest.raises(ValueError, match=message):
        validate_runtime_config(config)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("port", 0, "server.port must be between 1 and 65535"),
        ("port", 65536, "server.port must be between 1 and 65535"),
        ("workers", 0, "server.workers must be greater than 0"),
        ("workers", 65, "server.workers must be <= 64"),
        ("shutdown_timeout_seconds", 0, "server.shutdown_timeout_seconds must be greater than 0"),
        ("shutdown_timeout_seconds", 301, "server.shutdown_timeout_seconds must be <= 300"),
    ],
)
def test_server_config_validation(field, value, message):
    config = production_config()
    setattr(config.server, field, value)

    with pytest.raises(ValueError, match=message):
        validate_runtime_config(config)


def test_production_mode_rejects_debug_sensitive_logging_and_missing_secrets():
    config = production_config()
    config.app.debug = True

    with pytest.raises(ValueError, match="app.debug must be false in production"):
        validate_runtime_config(config)

    config = production_config()
    config.agent.log_full_sql = True
    with pytest.raises(ValueError, match="agent.log_full_sql must be false in production"):
        validate_runtime_config(config)

    config = production_config()
    config.agent.expose_raw_rows_to_client = True
    with pytest.raises(ValueError, match="agent.expose_raw_rows_to_client must be false in production"):
        validate_runtime_config(config)

    config = production_config()
    config.llm.api_key = "changeme"
    with pytest.raises(ValueError, match="llm.api_key"):
        validate_runtime_config(config)
