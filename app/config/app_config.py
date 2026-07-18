from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config.config_loader import load_config
from app.security.data_masking import DEFAULT_SENSITIVE_FIELDS
from app.security.sql_security import BANNED_FUNCTIONS


@dataclass
class AppMetaConfig:
    environment: str = "development"
    debug: bool = True


@dataclass
class File:
    enable: bool = True
    level: str = "INFO"
    path: str = "logs"
    rotation: str = "10 MB"
    retention: str = "7 days"


@dataclass
class Console:
    enable: bool = True
    level: str = "INFO"


@dataclass
class LoggingConfig:
    file: File = field(default_factory=File)
    console: Console = field(default_factory=Console)


@dataclass
class DBConfig:
    host: str = "localhost"
    port: int = 3307
    user: str = "ghy"
    password: str = ""
    database: str = ""


@dataclass
class QdrantConfig:
    host: str = "localhost"
    port: int = 6333
    embedding_size: int = 1024


@dataclass
class EmbeddingConfig:
    host: str = "localhost"
    port: int = 8081
    model: str = "BAAI/bge-large-zh-v1.5"


@dataclass
class ESConfig:
    host: str = "localhost"
    port: int = 9200
    index_name: str = "data-agent-value"


@dataclass
class LLMConfig:
    model_name: str = "deepseek-ai/DeepSeek-V3"
    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1"
    temperature: float = 0
    timeout_seconds: int = 30
    max_retries: int = 2


@dataclass
class AgentConfig:
    max_sql_retries: int = 2
    max_result_rows: int = 200
    result_sample_rows: int = 20
    query_timeout_seconds: int = 10
    llm_output_parse_retries: int = 2
    allow_select_star: bool = False
    expose_sql_to_client: bool = False
    expose_raw_rows_to_client: bool = False
    max_sse_payload_bytes: int = 262144
    disconnect_poll_interval_seconds: float = 0.2
    sse_queue_maxsize: int = 100
    token_batch_chars: int = 80
    max_candidate_tables: int = 10
    max_candidate_metrics: int = 10
    max_estimated_rows: int = 100000
    max_join_tables: int = 8
    reject_full_table_scan: bool = False
    reject_filesort: bool = False
    reject_temporary_table: bool = False
    reject_on_cost_error: bool = False
    expose_trace_to_client: bool = False
    log_full_sql: bool = False
    banned_sql_functions: list[str] = field(default_factory=lambda: sorted(BANNED_FUNCTIONS))


@dataclass
class SecurityConfig:
    sensitive_fields: list[str] = field(default_factory=lambda: sorted(DEFAULT_SENSITIVE_FIELDS))


@dataclass
class MetadataSyncConfig:
    max_values_per_column: int = 5000
    batch_size: int = 100


@dataclass
class AppConfig:
    app: AppMetaConfig = field(default_factory=AppMetaConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    db_meta: DBConfig = field(default_factory=DBConfig)
    db_dw: DBConfig = field(default_factory=DBConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    es: ESConfig = field(default_factory=ESConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    metadata_sync: MetadataSyncConfig = field(default_factory=MetadataSyncConfig)


config_file = Path(__file__).parents[2] / "conf" / "app_config.yaml"
app_config: AppConfig = load_config(AppConfig, config_file)


def validate_runtime_config(config: AppConfig = app_config) -> None:
    placeholder_values = {"", "your_siliconflow_api_key_here", "changeme", "change_me"}
    if config.llm.api_key.strip() in placeholder_values:
        raise ValueError("llm.api_key is not configured")
    if config.db_dw.user.lower() == "root":
        raise ValueError("Agent DW database user must not be root")
    if config.agent.max_result_rows <= 0:
        raise ValueError("agent.max_result_rows must be greater than 0")
    if config.agent.result_sample_rows <= 0:
        raise ValueError("agent.result_sample_rows must be greater than 0")
    if config.agent.result_sample_rows > config.agent.max_result_rows:
        raise ValueError("agent.result_sample_rows must be <= agent.max_result_rows")
    if config.agent.query_timeout_seconds <= 0:
        raise ValueError("agent.query_timeout_seconds must be greater than 0")
    if config.agent.llm_output_parse_retries < 0:
        raise ValueError("agent.llm_output_parse_retries must be >= 0")
    if config.agent.max_sse_payload_bytes < 4096:
        raise ValueError("agent.max_sse_payload_bytes is too small")
    if config.agent.max_estimated_rows <= 0:
        raise ValueError("agent.max_estimated_rows must be greater than 0")
    if config.agent.max_join_tables <= 0:
        raise ValueError("agent.max_join_tables must be greater than 0")
    if config.agent.disconnect_poll_interval_seconds <= 0:
        raise ValueError("agent.disconnect_poll_interval_seconds must be greater than 0")
    if config.agent.sse_queue_maxsize <= 0:
        raise ValueError("agent.sse_queue_maxsize must be greater than 0")
    if config.agent.token_batch_chars <= 0:
        raise ValueError("agent.token_batch_chars must be greater than 0")
    if config.metadata_sync.max_values_per_column <= 0:
        raise ValueError("metadata_sync.max_values_per_column must be greater than 0")
    if config.metadata_sync.batch_size <= 0:
        raise ValueError("metadata_sync.batch_size must be greater than 0")
