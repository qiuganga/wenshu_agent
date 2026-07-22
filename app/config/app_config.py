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
class RuntimeConfig:
    environment: str = "dev"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    shutdown_timeout_seconds: float = 5


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
    json_format: bool = False


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
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    key_prefix: str = "wenshu-agent"
    socket_timeout_seconds: float = 2


@dataclass
class TelemetryConfig:
    enabled: bool = True
    service_name: str = "wenshu-agent"
    exporter: str = "console"


@dataclass
class LLMConfig:
    model_name: str = "deepseek-ai/DeepSeek-V3"
    default_model: str = ""
    fallback_model: str = ""
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
    result_sample_value_max_chars: int = 500
    query_timeout_seconds: int = 10
    llm_output_parse_retries: int = 2
    allow_select_star: bool = False
    expose_sql_to_client: bool = False
    expose_raw_rows_to_client: bool = False
    max_sse_payload_bytes: int = 262144
    disconnect_poll_interval_seconds: float = 0.2
    sse_queue_maxsize: int = 100
    sse_put_timeout_seconds: float = 1
    max_concurrent_queries: int = 20
    max_concurrent_queries_per_user: int = 3
    admission_timeout_seconds: float = 2
    request_dedup_ttl_seconds: float = 30
    request_dedup_max_entries: int = 1000
    query_total_timeout_seconds: float = 60
    checkpoint_ttl_seconds: int = 3600
    token_batch_chars: int = 80
    max_candidate_tables: int = 10
    max_candidate_metrics: int = 10
    max_estimated_rows: int = 100000
    max_query_cost: float = 100000.0
    max_join_tables: int = 8
    max_full_scan_fact_tables: int = 0
    max_unknown_full_scan_rows: int = 10000
    allow_dimension_full_scan: bool = True
    explain_timeout_seconds: int = 5
    reject_full_table_scan: bool = False
    reject_filesort: bool = False
    reject_temporary_table: bool = False
    reject_on_cost_error: bool = False
    expose_trace_to_client: bool = False
    log_full_sql: bool = False
    banned_sql_functions: list[str] = field(default_factory=lambda: sorted(BANNED_FUNCTIONS))


@dataclass
class PromptConfig:
    version_enabled: bool = True
    default_version: str = "v1"


@dataclass
class CostConfig:
    enabled: bool = True


@dataclass
class CacheConfig:
    enabled: bool = True
    exact_enabled: bool = True
    semantic_enabled: bool = True
    exact_ttl_seconds: int = 300
    semantic_ttl_seconds: int = 900
    semantic_similarity_threshold: float = 0.92
    semantic_top_k: int = 5
    max_entry_bytes: int = 65536
    lease_ttl_seconds: int = 30
    lease_wait_timeout_seconds: float = 5
    namespace_version: str = "v1"
    data_version: str = "v1"
    semantic_collection_name: str = "wenshu_agent_semantic_cache"
    cache_safe_final_summary: bool = False


@dataclass
class SecurityConfig:
    sensitive_fields: list[str] = field(default_factory=lambda: sorted(DEFAULT_SENSITIVE_FIELDS))
    production_mode: bool = False


@dataclass
class MetadataSyncConfig:
    max_values_per_column: int = 5000
    batch_size: int = 100


@dataclass
class AppConfig:
    app: AppMetaConfig = field(default_factory=AppMetaConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    db_meta: DBConfig = field(default_factory=DBConfig)
    db_dw: DBConfig = field(default_factory=DBConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    es: ESConfig = field(default_factory=ESConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    metadata_sync: MetadataSyncConfig = field(default_factory=MetadataSyncConfig)


config_file = Path(__file__).parents[2] / "conf" / "app_config.yaml"
app_config: AppConfig = load_config(AppConfig, config_file)


def validate_runtime_config(config: AppConfig = app_config) -> None:
    placeholder_values = {"", "your_siliconflow_api_key_here", "changeme", "change_me"}
    if config.llm.api_key.strip() in placeholder_values:
        raise ValueError("llm.api_key is not configured")
    if not (config.llm.default_model or config.llm.model_name).strip():
        raise ValueError("llm.default_model or llm.model_name must not be empty")
    if config.db_dw.user.lower() == "root":
        raise ValueError("Agent DW database user must not be root")
    if config.agent.max_result_rows <= 0:
        raise ValueError("agent.max_result_rows must be greater than 0")
    if config.agent.result_sample_rows <= 0:
        raise ValueError("agent.result_sample_rows must be greater than 0")
    if config.agent.result_sample_value_max_chars <= 0:
        raise ValueError("agent.result_sample_value_max_chars must be greater than 0")
    if config.agent.result_sample_value_max_chars > 5000:
        raise ValueError("agent.result_sample_value_max_chars must be <= 5000")
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
    if config.agent.max_estimated_rows > 1_000_000_000:
        raise ValueError("agent.max_estimated_rows must be <= 1000000000")
    if config.agent.max_query_cost <= 0:
        raise ValueError("agent.max_query_cost must be greater than 0")
    if config.agent.max_query_cost > 1_000_000_000:
        raise ValueError("agent.max_query_cost must be <= 1000000000")
    if config.agent.max_join_tables <= 0:
        raise ValueError("agent.max_join_tables must be greater than 0")
    if config.agent.max_join_tables > 64:
        raise ValueError("agent.max_join_tables must be <= 64")
    if config.agent.max_full_scan_fact_tables < 0:
        raise ValueError("agent.max_full_scan_fact_tables must be >= 0")
    if config.agent.max_full_scan_fact_tables > config.agent.max_join_tables:
        raise ValueError("agent.max_full_scan_fact_tables must be <= agent.max_join_tables")
    if config.agent.max_unknown_full_scan_rows < 1:
        raise ValueError("agent.max_unknown_full_scan_rows must be >= 1")
    if config.agent.max_unknown_full_scan_rows > config.agent.max_estimated_rows:
        raise ValueError("agent.max_unknown_full_scan_rows must be <= agent.max_estimated_rows")
    if config.agent.explain_timeout_seconds <= 0:
        raise ValueError("agent.explain_timeout_seconds must be greater than 0")
    if config.agent.explain_timeout_seconds > 60:
        raise ValueError("agent.explain_timeout_seconds must be <= 60")
    if config.agent.disconnect_poll_interval_seconds <= 0:
        raise ValueError("agent.disconnect_poll_interval_seconds must be greater than 0")
    if config.agent.sse_queue_maxsize <= 0:
        raise ValueError("agent.sse_queue_maxsize must be greater than 0")
    if config.agent.sse_put_timeout_seconds <= 0:
        raise ValueError("agent.sse_put_timeout_seconds must be greater than 0")
    if config.agent.sse_put_timeout_seconds > 30:
        raise ValueError("agent.sse_put_timeout_seconds must be <= 30")
    if config.agent.max_concurrent_queries <= 0:
        raise ValueError("agent.max_concurrent_queries must be greater than 0")
    if config.agent.max_concurrent_queries > 10000:
        raise ValueError("agent.max_concurrent_queries must be <= 10000")
    if config.agent.max_concurrent_queries_per_user <= 0:
        raise ValueError("agent.max_concurrent_queries_per_user must be greater than 0")
    if config.agent.max_concurrent_queries_per_user > config.agent.max_concurrent_queries:
        raise ValueError("agent.max_concurrent_queries_per_user must be <= agent.max_concurrent_queries")
    if config.agent.admission_timeout_seconds <= 0:
        raise ValueError("agent.admission_timeout_seconds must be greater than 0")
    if config.agent.admission_timeout_seconds > 60:
        raise ValueError("agent.admission_timeout_seconds must be <= 60")
    if config.agent.request_dedup_ttl_seconds <= 0:
        raise ValueError("agent.request_dedup_ttl_seconds must be greater than 0")
    if config.agent.request_dedup_ttl_seconds > 86400:
        raise ValueError("agent.request_dedup_ttl_seconds must be <= 86400")
    if config.agent.request_dedup_max_entries <= 0:
        raise ValueError("agent.request_dedup_max_entries must be greater than 0")
    if config.agent.request_dedup_max_entries > 1_000_000:
        raise ValueError("agent.request_dedup_max_entries must be <= 1000000")
    if config.agent.query_total_timeout_seconds <= 0:
        raise ValueError("agent.query_total_timeout_seconds must be greater than 0")
    if config.agent.query_total_timeout_seconds > 3600:
        raise ValueError("agent.query_total_timeout_seconds must be <= 3600")
    if config.agent.checkpoint_ttl_seconds <= 0:
        raise ValueError("agent.checkpoint_ttl_seconds must be greater than 0")
    if config.agent.checkpoint_ttl_seconds > 86400:
        raise ValueError("agent.checkpoint_ttl_seconds must be <= 86400")
    if config.agent.token_batch_chars <= 0:
        raise ValueError("agent.token_batch_chars must be greater than 0")
    if config.metadata_sync.max_values_per_column <= 0:
        raise ValueError("metadata_sync.max_values_per_column must be greater than 0")
    if config.metadata_sync.batch_size <= 0:
        raise ValueError("metadata_sync.batch_size must be greater than 0")
    if config.redis.port <= 0 or config.redis.port > 65535:
        raise ValueError("redis.port must be between 1 and 65535")
    if config.redis.db < 0:
        raise ValueError("redis.db must be >= 0")
    if config.redis.socket_timeout_seconds <= 0:
        raise ValueError("redis.socket_timeout_seconds must be greater than 0")
    if not config.redis.key_prefix.strip():
        raise ValueError("redis.key_prefix must not be empty")
    if not config.telemetry.service_name.strip():
        raise ValueError("telemetry.service_name must not be empty")
    if config.telemetry.exporter not in {"console", "none"}:
        raise ValueError("telemetry.exporter must be console or none")
    if not config.prompt.default_version.strip():
        raise ValueError("prompt.default_version must not be empty")
    if config.cache.exact_ttl_seconds <= 0:
        raise ValueError("cache.exact_ttl_seconds must be greater than 0")
    if config.cache.semantic_ttl_seconds <= 0:
        raise ValueError("cache.semantic_ttl_seconds must be greater than 0")
    if not 0 < config.cache.semantic_similarity_threshold <= 1:
        raise ValueError("cache.semantic_similarity_threshold must be between 0 and 1")
    if config.cache.semantic_top_k <= 0:
        raise ValueError("cache.semantic_top_k must be greater than 0")
    if config.cache.semantic_top_k > 100:
        raise ValueError("cache.semantic_top_k must be <= 100")
    if config.cache.max_entry_bytes < 1024:
        raise ValueError("cache.max_entry_bytes must be >= 1024")
    if config.cache.max_entry_bytes > 1_048_576:
        raise ValueError("cache.max_entry_bytes must be <= 1048576")
    if config.cache.lease_ttl_seconds <= 0:
        raise ValueError("cache.lease_ttl_seconds must be greater than 0")
    if config.cache.lease_wait_timeout_seconds <= 0:
        raise ValueError("cache.lease_wait_timeout_seconds must be greater than 0")
    if config.cache.lease_wait_timeout_seconds >= config.cache.lease_ttl_seconds:
        raise ValueError("cache.lease_wait_timeout_seconds must be less than cache.lease_ttl_seconds")
    if not config.cache.namespace_version.strip():
        raise ValueError("cache.namespace_version must not be empty")
    if not config.cache.data_version.strip():
        raise ValueError("cache.data_version must not be empty")
    if not config.cache.semantic_collection_name.strip():
        raise ValueError("cache.semantic_collection_name must not be empty")
    if config.runtime.environment not in {"dev", "test", "prod"}:
        raise ValueError("runtime.environment must be dev, test or prod")
    if config.server.port <= 0 or config.server.port > 65535:
        raise ValueError("server.port must be between 1 and 65535")
    if config.server.workers <= 0:
        raise ValueError("server.workers must be greater than 0")
    if config.server.workers > 64:
        raise ValueError("server.workers must be <= 64")
    if config.server.shutdown_timeout_seconds <= 0:
        raise ValueError("server.shutdown_timeout_seconds must be greater than 0")
    if config.server.shutdown_timeout_seconds > 300:
        raise ValueError("server.shutdown_timeout_seconds must be <= 300")
    if config.security.production_mode or config.runtime.environment == "prod":
        if config.app.debug:
            raise ValueError("app.debug must be false in production")
        if config.agent.log_full_sql:
            raise ValueError("agent.log_full_sql must be false in production")
        if config.agent.expose_raw_rows_to_client:
            raise ValueError("agent.expose_raw_rows_to_client must be false in production")
        if config.llm.api_key.strip() in placeholder_values:
            raise ValueError("llm.api_key must be configured in production")
        if config.db_dw.password.strip() in placeholder_values:
            raise ValueError("db_dw.password must be configured in production")
        if config.db_meta.password.strip() in placeholder_values:
            raise ValueError("db_meta.password must be configured in production")
