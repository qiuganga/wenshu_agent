from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config.config_loader import load_config


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
    query_timeout_seconds: int = 10
    max_candidate_tables: int = 10
    max_candidate_metrics: int = 10
    log_full_sql: bool = False


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


config_file = Path(__file__).parents[2] / "conf" / "app_config.yaml"
app_config: AppConfig = load_config(AppConfig, config_file)


def validate_runtime_config(config: AppConfig = app_config) -> None:
    placeholder_values = {"", "your_siliconflow_api_key_here", "changeme"}
    if config.llm.api_key.strip() in placeholder_values:
        raise ValueError("llm.api_key is not configured")
    if config.db_dw.user.lower() == "root":
        raise ValueError("Agent DW database user must not be root")
